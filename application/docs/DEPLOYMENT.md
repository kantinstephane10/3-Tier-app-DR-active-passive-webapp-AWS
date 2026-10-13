# Deploy the application with Jenkins only

The root Jenkinsfile on main deploys and sets up AWS infrastructure. The application Jenkinsfile on this feature branch builds and releases code to that environment. Jenkins is the deployment orchestrator; AWS CLI/SSM execute its commands on private instances. S3 stores immutable release files. Parameter Store holds release pointers and a regional deployment lease. No CodeDeploy agent, application, group or AppSpec is needed.

## 1. Main infrastructure job setup contract

Run your existing main-branch infrastructure job through the required rollout first. Prepare primary us-east-1 before DR us-west-2. The infrastructure/setup owner must provide:

- Existing web and app ASGs, with at least two healthy InService instances each, correctly attached target groups and a stable desired count.
- Existing web port 80, internal ALB/app port 8080, RDS port 5432 and `/health` target checks. App instances have no public IP or inbound public management port.
- An SSM agent on every app/web host and the management/migration host, online through NAT/endpoints with their instance profiles.
- Node.js 24, nginx on web hosts, AWS CLI, reviewed runtime scripts and protected regional env files in the main-owned AMI/launch-template setup.
- A private versioned regional artifact bucket using SSE-KMS, plus access policies described below. This is release storage, not a Terraform backend.
- Protected regional app/migrator secrets, database roles and access to the existing RDS PostgreSQL database.
- A management/bastion instance permitted to reach RDS and run migrations over SSM. It may be the existing primary bastion; no new public access is required.

The app pipeline validates those prerequisites, identifies ASG members and stops if setup is incomplete. It never runs Terraform, creates replacement AWS infrastructure or changes launch templates. The current main templates still run a Python demo, so their owner needs to add this setup contract before enabling application DEPLOY. Follow REPOSITORY-INTEGRATION.md for the handoff.

## 2. Database setup against the existing RDS instance

Main currently creates PostgreSQL database `app`. Use that existing database in production secrets; do not create a second RDS instance. Through an approved private management session, its database administrator prepares a migrator and restricted runtime role. Enter generated passwords at psql prompts, not in Git or shell arguments:

```sql
CREATE ROLE orders_migrator LOGIN;
\password orders_migrator
CREATE ROLE orders_app LOGIN;
\password orders_app
GRANT CONNECT ON DATABASE app TO orders_migrator, orders_app;
GRANT USAGE, CREATE ON SCHEMA public TO orders_migrator WITH GRANT OPTION;
```

Connect to database `app` before granting its schema permissions. The migrator creates/owns the v1 application tables and grants the runtime role only SELECT/INSERT/UPDATE permissions required by the API/worker. It needs no AWS database-creation permission. App processes cannot perform schema DDL, change catalog prices or administer roles. Future migrations must remain compatible with both the old running release and rollback; application rollback does not undo DDL.

The main setup workflow can automate this approved DB-role initialization. It must not expose the managed RDS master password in Jenkins logs or use it as the runtime app secret.

## 3. Regional Secrets Manager configuration

The infrastructure owner creates primary app JSON with the following fields:

```json
{
  "host": "EXISTING-PRIMARY-RDS-ENDPOINT",
  "port": 5432,
  "dbname": "app",
  "username": "orders_app",
  "password": "GENERATED-RUNTIME-PASSWORD",
  "sessionSecret": "RANDOM-64-HEX-CHARACTER-KEY"
}
```

Generate a session key with `openssl rand -hex 32`. The separate migration secret uses the same DB/endpoint/port and the orders_migrator username/password; it does not require a sessionSecret. On DR use a separate app secret with the replica endpoint and the same replicated password/session key. Copying the primary hostname unchanged to DR is incorrect. Keep WRITE_ENABLED=false on DR until fenced, coordinated database promotion.

Production connects to RDS with certificate verification. Main setup installs the AWS RDS global CA bundle. Passwords stay in Secrets Manager; env files contain only secret ARNs and configuration. This application reads secrets at startup, so restart processes after rotation.

## 4. Main-owned AMI/launch-template bootstrap

The following reviewed commands illustrate the host setup that the infrastructure job/AMI build must perform; app DEPLOY does not run these provisioning commands:

```bash
# App AMI/launch-template setup, region-specific:
sudo bash application/scripts/provision-ubuntu.sh app us-east-1
sudo install -m 0600 application/deploy/app.env.example /etc/kantin-orders/app.env
# Fill the existing app secret ARN; PORT=8080, WRITE_ENABLED=true in primary.
sudo bash application/deploy/bootstrap-unit.sh app us-east-1 /kt-orders/us-east-1/app/release

# Web AMI/launch-template setup:
sudo bash application/scripts/provision-ubuntu.sh web us-east-1
sudo install -m 0600 application/deploy/web.env.example /etc/kantin-orders/web.env
# Set AWS_REGION and the existing internal ALB DNS; its listener port is 8080.
sudo bash application/deploy/bootstrap-unit.sh web us-east-1 /kt-orders/us-east-1/web/release
```

Populate env files before enabling bootstrap; the examples are placeholders. In standby replace region, secret ARN, internal DNS and parameter paths, and set WRITE_ENABLED=false. The provisioning script installs `/usr/local/bin/kantin-release`, `kantin-bootstrap`, and the web configuration/smoke helper. It installs neither a CodeDeploy agent nor an SSH deploy key.

Bake tools/env/bootstrap units into the main-owned launch-template setup so every new instance inherits them. The bootstrap service retrieves the currently published revision, verifies its immutable S3 version/hash and installs it. It waits up to ten minutes for a first release; main must select suitable initial health grace/capacity settings. Do the first BUILD_ONLY before the first live release so host preparation and pipeline readiness are verified early.

For the migration host, main setup installs AWS CLI/SSM, Node.js and the RDS CA, then the existing migration helper and its protected config:

```bash
sudo bash application/scripts/provision-ubuntu.sh runner us-east-1
sudo install -m 0755 application/scripts/migration-runner.sh /usr/local/bin/kantin-migrate
sudo install -m 0600 application/deploy/migration.env.example /etc/kantin-orders/migration.env
```

Fill its existing migration secret ARN. For an older directory-based release at `/opt/kantin-orders/application` or `/opt/kantin-orders/web`, stop services, retain a backup and convert that path to a versioned-release symlink before using this installer. The supplied Python demo has no such directory, so this conversion usually does not apply.

## 5. Permissions provided by the infrastructure owner

| Identity | Scoped permissions |
|---|---|
| Jenkins deployment role | Describe ASGs/target health/SSM status; suspend/resume the specified ASG processes; deregister/register their targets; SendCommand and inspect commands on app/web/migration instances; GetBucketVersioning/PutObject and required KMS encrypt/data-key access; Get/Put/DeleteParameter only for this app's release pointers and lease |
| App instance role | SSM management; GetObjectVersion/KMS decrypt on regional releases; read its release pointer; GetSecretValue/decrypt only for its app secret |
| Web instance role | SSM management; GetObjectVersion/KMS decrypt on regional releases; read its release pointer; no DB/migrator secret access |
| Migration host role | SSM management; read release files; GetSecretValue/decrypt only for its migration secret; permitted TCP access to RDS |

Scope SendCommand to the reviewed management instances/ASG instance tags and AWS-RunShellScript. Jenkins does not need to read DB secrets. Protect the Jenkins agent, branch, installer/config, release objects, pointer and lease write permissions. SSM runs installation commands with root privileges, so this remains trusted deployment code.

Use short-lived role credentials on Jenkins when possible. For an existing external agent, Jenkins Secret text credentials can bind AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY and, when applicable, AWS_SESSION_TOKEN around both deployment and recovery steps. Never commit keys. If you use scoped Credentials Binding rather than an agent role, the post-build recovery step needs the same binding as deploy.

## 6. Configure the application job

Install Node.js 24, Python 3, Git, AWS CLI, Docker for disposable PostgreSQL tests, Gitleaks 8.30.1 and Trivy 0.75.0 on a trusted agent labeled aws-orders-ci. Install the scanners using `sudo bash application/scripts/install-security-tools-ubuntu.sh`. Production EC2 services run directly under systemd; Docker is only used by CI tests.

Jenkins plugins: Pipeline, Git, Credentials Binding, Timestamper, JUnit and Pipeline: Input Step. Use a separate Pipeline from SCM job:

- Branch: feat/jenkins-only-app-deployment.
- Script path: application/Jenkinsfile.
- Full Git checkout; disable shallow cloning.
- Trusted SCM checkout credentials when required.
- SECURITY_APPROVERS: an existing trusted Jenkins group or user IDs.

The infrastructure job stays on main with script path Jenkinsfile. Do not run it during an application rollout. The app lease serializes app jobs in a region but does not lock the existing main infrastructure job.

## 7. Configure the handoff

Fill application/deploy/regions.json from the main job's outputs and existing resources: artifact bucket, regional KMS ARN, app/web ASG names, attached target group ARNs, migration host ID and distinct release/lease parameter paths. No password belongs in this JSON. Inspect the regional ASG's target groups or use AWS CLI DescribeAutoScalingGroups to get their exact ARNs. Optional publicUrl can use main's CloudFront URL; leave it null for regional-only tests until global routing is ready.

The defaults use the root infrastructure ports and `/health` alias. Regional tests execute on a web host over SSM and localhost, so no public test rule, regional certificate or SSH access is added. Optional publicUrl verifies the active region over HTTPS. Main's CloudFront setup must forward API methods, session cookies and CSRF/idempotency headers without caching.

## 8. Build, approve and release

Run BUILD_ONLY first. It installs dependencies, runs syntax/delivery tests and PostgreSQL integration tests, scans secrets/dependencies/config, builds two release ZIPs and produces a SHA-256 manifest.

Run DEPLOY for us-east-1 after main setup is ready. Jenkins checks manifest/bundle hashes, takes a regional lease, validates hosts, uploads encrypted versioned artifacts and records previous pointers/settings. It temporarily freezes ASG launch/termination/health/automatic scaling processes to keep the inventory stable during rollout. It records exactly which processes it changed so prior manual suspensions remain untouched.

In active mode it runs one schema migration through the private management host, then publishes the app pointer. It drains one app target, installs/validates the release via SSM, re-registers it and waits for ALB health before moving to the next. It then does the same for web targets and runs checkout/idempotency/worker smoke checks through a web host. It never deliberately removes the last healthy target. Bootstrap uses the published pointers for future instances after settings are restored.

Only CRITICAL findings (including detected secrets and unknown severity) require authorized approval and a reason. LOW/MEDIUM/HIGH continue automatically. Scanner/test/setup/migration/rollout errors block deployment without a risk waiver. Blank approval, rejection or timeout stops the build. Approval is tied to this build and its manifest hash.

Deploy us-west-2 after replica/schema/grants and DR setup are verified. Mode=standby skips migrations; smoke verifies DB access but rejects checkout and writable readiness. Keep one writable region. Deploy the same reviewed source commit to both regions; build identifiers differ.

## 9. Failure and interruption handling

A failed host install attempts to restore its previous local symlink/services. A failed rollout or smoke test restores published pointers and attempts to roll attempted hosts back to the previously published release. First deployment has no published prior version; report/repair a partial initial release rather than assuming a full automatic rollback exists. Database migrations remain applied.

The driver restores the ASG processes it added and clears its lease on normal cleanup. If restoration or cleanup fails, the deployment report names the affected group and the lease stays as a guard. The Jenkins post step also checks recovery metadata for that exact release. It refuses to alter another build's lease and retains an interrupted lease for inspection.

If the agent is lost or the job is force-killed, first confirm no deployment is still running, inspect SSM commands, targets, installed versions and release pointers. Use the recorded release ID to restore only the captured ASG settings:

```bash
cd application
python3 scripts/resume-autoscaling.py us-east-1 THE_RECORDED_RELEASE_ID
```

After validating/reconciling the application and confirming settings are restored, the operator can clear the matching lease:

```bash
aws --region us-east-1 ssm delete-parameter --name /kt-orders/us-east-1/deployment-lease
```

Do not delete another active build's lease or accept a mixed deployment without inspection. Check rollbackErrors/resumeErrors in reports/deployment.json. Normal rollback is best effort and can fail when access, capacity or an instance fails; it is not a guarantee of uninterrupted availability. Release directories are retained on hosts; perform reviewed cleanup after your rollback window to avoid disk exhaustion.

## 10. Validate operations

Use SSM sessions/commands to inspect `systemctl status kantin-api kantin-worker`, `journalctl -u kantin-api -u kantin-worker`, nginx health and app `curl -fsS http://127.0.0.1:8080/health/deploy`. Runtime logs omit credentials/payloads. Existing CloudWatch setup can collect them; application deployment does not create monitoring infrastructure.

Main's old smoke script expects demo JSON at `/`; its owner must adjust it for the storefront/API after adoption. Tests in this source checkout are not evidence of an actual AWS rollout, recovery drill or backup restore. Use RECOVERY.md for a coordinated DR drill after both regional releases are verified.

Official references:
- https://docs.aws.amazon.com/systems-manager/latest/userguide/example_ssm_SendCommand_section.html
- https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-register-targets.html
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PostgreSQL.Replication.ReadReplicas.html
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/high_availability_origin_failover.html
