# Deploy to the EC2 architecture with Jenkins

Prepare the primary region (us-east-1) first, then standby (us-west-2). The application supports PostgreSQL; choose RDS PostgreSQL 17 for this lab, with a compatible cross-region replica. Provision the infrastructure in your diagram before application DEPLOY. BUILD_ONLY and local preview work without AWS infrastructure.

## 1. Required network paths

| Source | Destination | Allowed traffic |
|---|---|---|
| CloudFront | Public regional ALB | HTTPS 443; use the CloudFront origin-facing prefix list and an origin header rule |
| Regional test client/Jenkins | Public regional ALB test hostname | HTTPS 443 from explicitly allowed test egress only |
| Public ALB security group | Web EC2 security group | TCP 80 |
| Web EC2 security group | Internal ALB security group | TCP 80, or 443 with a valid certificate |
| Internal ALB security group | App EC2 security group | TCP 3000 |
| App EC2 and migration-runner security groups | RDS security group | TCP 5432 |
| EC2 instances | Required AWS APIs/package sources | NAT egress or the appropriate VPC endpoints |

Web and app EC2 instances have no public IPs. Use SSM for management; the diagram's bastion is not needed by this pipeline. Require IMDSv2. Attach instance profiles before bootstrapping. Use Ubuntu 24.04 amd64 with persistent launch-template settings and at least two instances per tier across two AZs for rolling deployment. RDS connection strings use its stable endpoint rather than individual database IPs.

ALB target groups: web target port 80; app target port 3000; health check `/health/deploy`, expected HTTP 200. Use `/health/ready` for active-region write readiness and external failover decisions. `/health/deploy` deliberately accepts a reachable standby database. On first launch targets can remain unhealthy until the initial app release is deployed. Keep enough healthy hosts during subsequent deployments.

## 2. Prepare database roles

Create an RDS PostgreSQL instance with Multi-AZ in us-east-1 and public access disabled. Leave its optional initial application database name empty; create `orders` below. From a permitted private-network administration host, connect to its default `postgres` database over verified TLS as the initial administrator. Create two roles and the application database. Enter generated passwords at the psql prompts; do not paste them in Git or shell command arguments.

```sql
CREATE ROLE orders_migrator LOGIN;
\password orders_migrator
CREATE ROLE orders_app LOGIN;
\password orders_app
CREATE DATABASE orders OWNER orders_migrator;
```

`orders_migrator` owns the `orders` database and performs schema changes. Runtime uses `orders_app`, which receives only SELECT/INSERT/UPDATE permissions needed by this application. The production migration command applies `db/grants.sql` after schema initialization. Do not use the RDS master account in the app secret. The database must be named `orders` for the supplied grant script; update that script deliberately if you choose another name.

Future schema changes must be backward compatible with the previous running release and rollback. Introduce versioned migrations and an expand/contract process before evolving this v1 schema. CodeDeploy rollback cannot undo database migrations.

## 3. Create regional Secrets Manager secrets

Generate a random session key on your workstation:

```bash
openssl rand -hex 32
```

In Secrets Manager, create the primary application secret as JSON:

```json
{
  "host": "YOUR-PRIMARY-RDS-ENDPOINT",
  "port": 5432,
  "dbname": "orders",
  "username": "orders_app",
  "password": "YOUR-GENERATED-APP-PASSWORD",
  "sessionSecret": "YOUR-GENERATED-64-HEX-CHARACTER-KEY"
}
```

Create a separate primary migration secret with the same host/dbname/port and the `orders_migrator` username/password. It does not need a sessionSecret. Each EC2 app role can read only its application secret and decrypt its KMS key; the migration-runner role can read only the migration secret.

After the primary schema exists, create the cross-region RDS replica. In us-west-2 create a separate application secret using the replica endpoint. Keep the app password and sessionSecret consistent with the replicated database and the primary region. Do not copy a primary-host secret unchanged to DR. Replication includes DB roles/grants; validate them in the secondary. Rotate passwords deliberately and restart services after secret changes, since this application loads secrets at process startup.

## 4. Prepare app and web launch templates

Place this project or its reviewed provisioning scripts in your AMI build/user-data process. On each app host:

```bash
sudo bash scripts/provision-ubuntu.sh app us-east-1
sudo install -m 0600 deploy/app.env.example /etc/kantin-orders/app.env
sudo nano /etc/kantin-orders/app.env
```

Set the real APP_SECRET_ARN and AWS_REGION. Keep WRITE_ENABLED=true in primary. In standby use `us-west-2`, its secret ARN and WRITE_ENABLED=false. The app env file contains configuration and a secret ARN, not a plaintext password. Node.js 24.19.0 is checksum verified by the provisioning script. Ubuntu 24.04 requires CodeDeploy agent 2.0.x or newer; verify the installed agent's version before creating deployment groups.

On each web host:

```bash
sudo bash scripts/provision-ubuntu.sh web us-east-1
sudo install -m 0600 deploy/web.env.example /etc/kantin-orders/web.env
sudo nano /etc/kantin-orders/web.env
```

Set INTERNAL_ALB_DNS to that region's internal load balancer. Use port 80 for this private-network lab, or port 443 plus INTERNAL_API_TLS_NAME matching a trusted certificate. The HTTPS option verifies the certificate. RDS connections always use verified TLS in production. Bake these files/settings into launch-template configuration or a protected bootstrap mechanism so new ASG instances inherit them. Do not manually configure only the first two instances.

## 5. Prepare the private migration runner

Use a dedicated SSM-managed management instance in the primary VPC for migrations. Your diagram's primary bastion can fill this role if you restrict its management access and give it the runner permissions below; a separate private runner provides stronger isolation. It permits TCP 5432 to RDS. Install AWS CLI v2 and SSM agent in its AMI, then:

```bash
sudo bash scripts/provision-ubuntu.sh runner us-east-1
sudo install -m 0755 scripts/migration-runner.sh /usr/local/bin/kantin-migrate
sudo install -m 0600 deploy/migration.env.example /etc/kantin-orders/migration.env
sudo nano /etc/kantin-orders/migration.env
```

Set the migration secret ARN and region. Its instance role needs SSM managed-instance permissions, GetSecretValue/decrypt for the migrator secret, and GetObjectVersion/decrypt for regional release artifacts. It does not serve application traffic. The pipeline sends an SSM command with only artifact bucket/key/version/hash; no DB credential passes through Jenkins or SSM command text.

## 6. Create artifact buckets and CodeDeploy groups

In each region create a private S3 artifact bucket with Block Public Access, versioning and SSE-KMS. Use a regional KMS key. Bucket names must be globally unique. Set lifecycle retention appropriate for your rollback window; do not expire a version still used by an ASG's last successful revision.

Create a CodeDeploy application named `kt-orders` in each region, compute platform EC2/On-premises. Give CodeDeploy its service role. Create these deployment groups:

| Region | Group | ASG/target group |
|---|---|---|
| us-east-1 | kt-orders-primary-app | Primary app ASG + internal app target group |
| us-east-1 | kt-orders-primary-web | Primary web ASG + public web target group |
| us-west-2 | kt-orders-secondary-app | Standby app ASG + internal app target group |
| us-west-2 | kt-orders-secondary-web | Standby web ASG + public web target group |

Select in-place deployments with load-balancer traffic control and CodeDeployDefault.OneAtATime, enable rollback on deployment failure/alarm and select relevant CloudWatch alarms. Associate the Auto Scaling groups so CodeDeploy installs the last successful revision on new instances. CodeDeploy integration with ASGs also requires working launch lifecycle hooks, instance profiles, artifact access and agent startup. Do not treat manual deployments to fixed EC2 IDs as an ASG deployment.

The app/web EC2 roles need GetObject/GetObjectVersion and KMS decrypt for their region's release bucket. App instances additionally need their application secret. App instances never need the migration secret. The CodeDeploy service role is separate from EC2 instance profiles.

## 7. Configure CloudFront and regional test hostnames

Use an owned domain with valid certificates. Create regional test hostnames pointing to each public ALB and allow only test-client/Jenkins egress for these hostnames. The pipeline smoke URLs must reach the selected region, not the global distribution that might still serve primary traffic.

On CloudFront use HTTPS to the regional public ALB, redirect viewer HTTP to HTTPS and forward all methods for `/api/*`. Apply CachingDisabled and forward Cookie, Content-Type, X-CSRF-Token and Idempotency-Key; forward the appropriate Host/origin domain for ALB certificate validation. Never cache `/api/session`, `/api/orders*` or `/api/status`, and never share Set-Cookie responses between viewers. For this v1 lab use CachingDisabled for the default behavior too, keeping releases consistent. ALB's CloudFront-only rule should require a secret origin header; maintain a separate restricted test rule.

Attach WAF managed rules and a rate-based rule on the dynamic order/session paths. The app intentionally supports anonymous demo sessions and cannot prevent guest-session recreation by itself. External TLS terminates at the public ALB; private web-to-app traffic is HTTP by default as shown in the lab configuration.

## 8. Configure Jenkins

Use a trusted Ubuntu agent labeled `aws-orders-ci` with Node.js 24, Python 3, Git, AWS CLI v2, Docker (for ephemeral DB tests), Gitleaks 8.30.1 and Trivy 0.75.0. Production EC2 deployment does not run Docker. Install scanners with:

```bash
sudo bash scripts/install-security-tools-ubuntu.sh
```

Install Pipeline, Git, Credentials Binding, Timestamper, JUnit and Pipeline: Input Step plugins. Ensure the agent OS user can run Docker; Docker access is privileged, so never run untrusted pull-request code on this agent. Allow outbound HTTPS to npm, release downloads, Trivy databases and required AWS APIs.

Use an EC2 instance profile or an assumed deployment role on the Jenkins agent. Scope it to regional artifact buckets/keys, both CodeDeploy applications/groups, and SendCommand/inspection for the migration runner. Required operations include s3:GetBucketVersioning, s3:PutObject, KMS encrypt/data-key operations, CodeDeploy CreateDeployment/GetDeployment and SSM SendCommand/ListCommandInvocations. Scope SendCommand to the reviewed runner and AWS-RunShellScript document. The Jenkins role does not need database passwords or Secrets Manager read access.

If your existing Jenkins agent uses environment credentials instead, store `aws-access-key-id` and `aws-secret-access-key` as Jenkins Secret text credentials and wrap only the deploy step with Credentials Binding:

```groovy
withCredentials([
  string(credentialsId: 'aws-access-key-id', variable: 'AWS_ACCESS_KEY_ID'),
  string(credentialsId: 'aws-secret-access-key', variable: 'AWS_SECRET_ACCESS_KEY')
]) {
  sh 'python3 scripts/deploy.py "$TARGET_REGION"'
}
```

Temporary credentials also require AWS_SESSION_TOKEN. Do not put keys in the Jenkinsfile, global plaintext settings, artifacts or Git. Prefer short-lived role credentials for AWS.

Replace SECURITY_APPROVERS in the Jenkinsfile with actual trusted Jenkins user IDs or a configured group. Jenkins administrators can also approve input. Approval is not needed for LOW/MEDIUM/HIGH; secret findings and unknown-severity findings count as CRITICAL. Rejection, blank justification or the 30-minute timeout blocks deployment. Tool, test, scan execution and migration failures always stop the build and cannot be waived. Approval identity, reason, release, region and manifest hash are archived. Never put a secret in the reason.

## 9. Push reviewed code and run BUILD_ONLY

Create an empty Git repository, then:

```bash
git init -b main
git add .
git commit -m "Add Kantin Supply application and EC2 delivery pipeline"
git remote add origin YOUR_GIT_REPOSITORY_URL
git push -u origin main
```

Check that Git contains no .env files, passwords or private keys. Protect main, Jenkinsfile and deployment/scanner configuration. In Jenkins create a Pipeline job from SCM, Git repository, branch */main, script path Jenkinsfile. Disable shallow checkout. Add read-only checkout credentials if private. The first build defaults to BUILD_ONLY. Inspect JUnit results, sanitized security reports, app.zip, web.zip and manifest.json.

## 10. Configure actual resources and release primary

Fill every primary field in `deploy/regions.json`: bucket, KMS key ARN, CodeDeploy names, migration runner instance ID and regional HTTPS smoke URL. Commit and push the reviewed configuration. Do not store passwords there.

Run ACTION=DEPLOY, TARGET_REGION=us-east-1. The build verifies manifest/bundle hashes, uploads versioned encrypted artifacts, runs migration/grants through SSM, deploys app, deploys web and verifies a real database-backed demo order with an idempotent retry and worker fulfillment. If critical findings exist, inspect reports and either fix/rebuild or record an authorized acceptance. This approval permits that exact build only.

When migration fails, no tier deployment starts. When an app deployment fails, web deployment does not start. CodeDeploy performs configured rollback for deployment failure/alarm. A post-deployment HTTP smoke failure fails Jenkins but does not automatically roll back a successful CodeDeploy release; investigate both tiers and roll back their recorded revisions together if needed. Database migration remains applied.

## 11. Release standby

Verify replica synchronization, schema version 1, replicated roles/grants and the DR application's secret. Confirm every standby app instance has WRITE_ENABLED=false. Complete the us-west-2 fields in regions.json. Run ACTION=DEPLOY, TARGET_REGION=us-west-2. No migration runs in standby; CodeDeploy health verifies DB access, while smoke tests confirm readiness and checkout return 503. Deploy the same reviewed application version to both regions; the build number differs but the source commit should match.

## 12. Inspect and operate

On app instances:

```bash
sudo systemctl status kantin-api kantin-worker
sudo journalctl -u kantin-api -u kantin-worker --since '15 minutes ago'
curl -fsS http://127.0.0.1:3000/health/deploy
```

On web instances check `sudo nginx -t`, `sudo systemctl status nginx` and `/health/deploy`. Send application and CodeDeploy logs to CloudWatch using your instance logging configuration. Monitor ALB errors/latency, EC2 capacity, RDS replica lag and connections, pending jobs and backups. A poison job or repeated worker error requires operator investigation; there is no automatic dead-letter policy in this DB-backed v1 worker.

Run the failover drill in RECOVERY.md only after both regional releases and backups have been verified. Autoscaling recovery and AWS Backup restore are infrastructure tests, not things this app can claim to have completed for you.

Official references:
- https://docs.aws.amazon.com/codedeploy/latest/userguide/integrations-aws-auto-scaling.html
- https://docs.aws.amazon.com/codedeploy/latest/userguide/reference-appspec-file-structure-hooks.html
- https://docs.aws.amazon.com/codedeploy/latest/userguide/codedeploy-agent.html
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PostgreSQL.Replication.ReadReplicas.html
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/high_availability_origin_failover.html
