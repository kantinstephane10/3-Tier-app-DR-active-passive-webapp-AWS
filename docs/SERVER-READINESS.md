# Prepare the existing servers for application deployment

Owner: **Kantin Tongue**. These are **manual preparation instructions**, performed outside this repository's app deployment pipeline. Jenkins deploys application files only. Complete the infrastructure workflow on `main` first. No Terraform, database setup or scaling operation runs from this app Jenkinsfile.

Examples assume existing Ubuntu 24.04 EC2 instances, RDS PostgreSQL, a private internal ALB with an HTTP listener on 8080, and an external ALB terminating HTTPS. Substitute the real ports and DNS names from your infrastructure outputs if they differ. Commands below run on the indicated host, not on Jenkins. Use a trusted admin session such as SSM.

## 1. Gather the existing infrastructure values

| Value | Used by |
| --- | --- |
| Primary and DR RDS endpoints, existing database name (examples use `app`) | Manual DB preparation and runtime secret |
| Internal ALB DNS and listener port | Web Nginx configuration |
| App/web EC2 instance IDs in each region | `deploy/targets.json` |
| Existing regional versioned S3 release bucket and KMS key ARN | `deploy/targets.json` |
| Runtime secret ARN in each region | App server environment |

Ask the infrastructure owner to make these existing paths available before release:

- External ALB → web tier port 80; users access the ALB over HTTPS.
- Web tier → internal ALB listener; internal ALB → app tier port 8080.
- App tier → RDS PostgreSQL port 5432. Restrict DB ingress to the app and approved private administration security groups.
- Existing SSM-managed app/web instances can reach SSM, S3 and required AWS endpoints. App instances also reach Secrets Manager.
- Existing target group health checks can use `/health/live` for process liveness. `/health` checks DB/schema readiness; `/health/ready` additionally requires writes and returns 503 on standby. The infrastructure owner chooses those settings; app Jenkins does not change them.

Check SSM → Fleet Manager / Managed nodes: every supplied instance must be online. Ubuntu AWS AMIs may already have SSM Agent; verify before installing it. [AWS Ubuntu SSM instructions](https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-ubuntu.html).

## 2. Prepare the database manually, once on the writable primary

Use a private administration host with network access to the existing RDS endpoint. Do not expose PostgreSQL publicly. If the database name is not `app`, substitute it in SQL, connection strings and the runtime secret.

```bash
sudo apt-get update
sudo apt-get install -y postgresql-client curl ca-certificates
curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /tmp/rds-global-bundle.pem
psql "host=YOUR_PRIMARY_RDS_ENDPOINT port=5432 dbname=app user=YOUR_DB_ADMIN sslmode=verify-full sslrootcert=/tmp/rds-global-bundle.pem" -W
```

Enter the existing admin password at the prompt. Inside `psql`, stop on errors, verify this is the writer, create the runtime role if it does not already exist, and set its password interactively:

```sql
\set ON_ERROR_STOP on
SHOW transaction_read_only;
-- Must be off. Do not initialize a read replica.
CREATE ROLE orders_app LOGIN;
\password orders_app
```

If `orders_app` already exists, skip `CREATE ROLE` and only change its password if intended. Keep the password in your password manager for the next step. Initialize this application's tables as the admin/owner in the existing `app` database. This is an initial setup example, not a migration workflow; review existing tables before applying it to a populated database. `IF NOT EXISTS` does not reconcile an incompatible schema.

```sql
BEGIN;
CREATE TABLE IF NOT EXISTS schema_versions (
  version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS products (
  id text PRIMARY KEY, name text NOT NULL, description text NOT NULL,
  category text NOT NULL, price_cents integer NOT NULL CHECK (price_cents > 0),
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS orders (
  id uuid PRIMARY KEY, customer_id uuid NOT NULL, idempotency_key uuid NOT NULL,
  request_hash text NOT NULL, status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','FULFILLED','CANCELLED')),
  total_cents integer NOT NULL CHECK (total_cents > 0),
  region text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (customer_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS orders_customer_created ON orders(customer_id,created_at DESC);
CREATE TABLE IF NOT EXISTS order_items (
  order_id uuid NOT NULL REFERENCES orders(id), product_id text NOT NULL REFERENCES products(id),
  name text NOT NULL, quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  price_cents integer NOT NULL CHECK (price_cents > 0), PRIMARY KEY (order_id, product_id)
);
CREATE TABLE IF NOT EXISTS jobs (
  order_id uuid PRIMARY KEY REFERENCES orders(id),
  completed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(created_at) WHERE completed_at IS NULL;
INSERT INTO products(id,name,description,category,price_cents) VALUES
  ('cloud-notebook','Cloud Architect Notebook','Plan your next architecture, one decision at a time.','Workspace',2400),
  ('desk-mat','Infrastructure Desk Mat','A clean foundation for your daily build.','Workspace',3900),
  ('travel-mug','On-call Travel Mug','Keep your coffee warm through the recovery drill.','Everyday',2800),
  ('hoodie','CloudOps Hoodie','Comfort for long debugging sessions.','Apparel',6900),
  ('tote','Deploy Day Tote','Carry the essentials for your next release.','Everyday',2200),
  ('sticker-pack','Architecture Sticker Pack','Six designs for your laptop and lab notebook.','Workspace',1200)
ON CONFLICT (id) DO NOTHING;
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
COMMIT;

GRANT CONNECT ON DATABASE app TO orders_app;
GRANT USAGE ON SCHEMA public TO orders_app;
GRANT SELECT ON products, schema_versions TO orders_app;
GRANT SELECT, INSERT, UPDATE ON orders, order_items, jobs TO orders_app;
```

Keep table ownership with the administration role. Do not grant the application superuser, table ownership or database creation rights. In a dedicated application database, remove PUBLIC schema creation privileges if compatible with your other workloads: `REVOKE CREATE ON SCHEMA public FROM PUBLIC;`. No sequence grants are needed for this UUID-based schema.

Exit and test the runtime identity separately:

```bash
psql "host=YOUR_PRIMARY_RDS_ENDPOINT port=5432 dbname=app user=orders_app sslmode=verify-full sslrootcert=/tmp/rds-global-bundle.pem" -W
```

```sql
SELECT version FROM schema_versions;
SELECT count(*) FROM products;
SHOW transaction_read_only;
\q
```

Expect version 1, six seeded products and `off` on the writer. For an existing replication-based DR database, initialize the primary only and verify the schema/data arrive on the replica. Do not run initialization SQL against a read-only standby. If your DR database is independently managed, its preparation is a separate DB administration responsibility. This guide and the app pipeline do not promote replicas or switch database endpoints.

[RDS PostgreSQL verified TLS documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

## 3. Store application runtime configuration in Secrets Manager

In each region, manually create or update an existing Secrets Manager **Other type of secret** containing this JSON. Fill values in the console; do not commit the completed JSON:

```json
{
  "host": "YOUR_REGIONAL_RDS_ENDPOINT",
  "port": 5432,
  "dbname": "app",
  "username": "orders_app",
  "password": "ENTER_THE_RUNTIME_ROLE_PASSWORD",
  "sessionSecret": "ENTER_A_RANDOM_VALUE_OF_AT_LEAST_32_CHARACTERS"
}
```

Generate the session value locally with `openssl rand -hex 32`. Keep the same session secret in both regions if sessions must survive a regional switch. The DR secret must reference the DR database endpoint; use credentials available on that database. A copied secret that still points to the primary is not a valid DR configuration.

Record each ARN. The existing app instance profile must permit `secretsmanager:GetSecretValue` on its regional secret and, where required, `kms:Decrypt` on its secret key. Jenkins does not need the DB secret. Rotating credentials requires a planned app/worker restart because this application loads the secret on process startup.

[Create a Secrets Manager secret](https://docs.aws.amazon.com/secretsmanager/latest/userguide/create_secret.html).

## 4. Prepare every app server manually

Install host tools and Node.js 24. These example Node downloads are pinned to 24.19.0 and checked against the official checksum file. Use `arm64` instead of `x64` for an ARM instance.

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates unzip xz-utils python3 util-linux
node_setup_dir=$(mktemp -d)
cd "$node_setup_dir"
curl -fsSLO https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz
curl -fsSLO https://nodejs.org/dist/v24.19.0/SHASUMS256.txt
awk '$2 == "node-v24.19.0-linux-x64.tar.xz" {print}' SHASUMS256.txt > node.sha256
test -s node.sha256
sha256sum -c node.sha256
tar -xf node-v24.19.0-linux-x64.tar.xz
sudo cp -a node-v24.19.0-linux-x64/. /usr/local/
/usr/local/bin/node --version
```

Install the AWS CLI v2 manually using [AWS's official Linux instructions](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html); verify `aws --version`. Do not run `aws configure` with static credentials on app/web hosts; use their existing instance profiles.

Create the local service user and configuration directory:

```bash
id kantin-orders >/dev/null 2>&1 || sudo useradd --system --user-group --home-dir /opt/kantin-orders --shell /usr/sbin/nologin kantin-orders
sudo install -d -m 0755 /opt/kantin-orders /etc/kantin-orders
sudo curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /etc/kantin-orders/rds-global-bundle.pem
sudo chmod 0644 /etc/kantin-orders/rds-global-bundle.pem
```

From a reviewed checkout of this feature branch, copy `deploy/app.env.example` to the app server as `/etc/kantin-orders/app.env`, then edit it:

```bash
sudo install -m 0600 deploy/app.env.example /etc/kantin-orders/app.env
sudoedit /etc/kantin-orders/app.env
```

```ini
NODE_ENV=production
PORT=8080
AWS_REGION=us-east-1
APP_SECRET_ARN=YOUR_REAL_REGIONAL_SECRET_ARN
DB_CA_FILE=/etc/kantin-orders/rds-global-bundle.pem
DB_SSL=true
WRITE_ENABLED=true
```

Use `us-west-2` and its secret on DR instances; set **`WRITE_ENABLED=false` on standby**. App and worker share this environment. Standby deployment does not enable writes or perform a failover.

Install the reference units from `deploy/` manually on each app host:

```bash
sudo chown root:root /etc/kantin-orders/app.env
sudo chmod 0600 /etc/kantin-orders/app.env
# Run these two copies where the reviewed deploy/ files are available on this host.
sudo install -m 0644 deploy/kantin-api.service /etc/systemd/system/kantin-api.service
sudo install -m 0644 deploy/kantin-worker.service /etc/systemd/system/kantin-worker.service
sudo systemctl daemon-reload
sudo systemctl enable kantin-api.service kantin-worker.service
```

Systemd reads the root-owned environment file before dropping privileges to `kantin-orders`. The CA and release directory must remain readable by that user. The units expect `/usr/local/bin/node` and `/opt/kantin-orders/application` (a symlink created by the release installer). **Do not start the services before the first release creates that path.** Jenkins starts/restarts them after copying the code; it does not install units or create users.

If the infrastructure installed a demonstration service on port 8080 (for example `aws-demo.service`), stop and disable that existing demo manually before the first app deployment:

```bash
# Only if this is the known demo unit on your host:
sudo systemctl disable --now aws-demo.service
sudo ss -ltnp 'sport = :8080'
```

Before the first release, port 8080 should be free. If `/opt/kantin-orders/application` is an old real directory, preserve it and manually convert it to a symlink to the preserved release during a planned maintenance window. The installer refuses to overwrite that directory.

## 5. Prepare every web server manually

```bash
sudo apt-get update
sudo apt-get install -y nginx curl ca-certificates unzip python3 util-linux
sudo install -d -m 0755 /opt/kantin-orders /etc/kantin-orders
```

Install/verify AWS CLI v2 and SSM as above. Create root-owned `/etc/kantin-orders/web.env` with the server's region (`us-west-2` on DR):

```bash
sudoedit /etc/kantin-orders/web.env
```

```ini
AWS_REGION=us-east-1
```

```bash
sudo chown root:root /etc/kantin-orders/web.env
sudo chmod 0600 /etc/kantin-orders/web.env
sudoedit /etc/nginx/sites-available/kantin-orders
```

Paste this server configuration. Replace `YOUR_INTERNAL_ALB_DNS` with the regional private ALB hostname, and port 8080 with its actual listener. `169.254.169.253` is the AWS VPC DNS resolver. Using a variable in `proxy_pass` lets Nginx refresh ALB DNS rather than keeping startup addresses indefinitely.

```nginx
server {
    listen 80 default_server;
    server_name _;
    root /opt/kantin-orders/web;
    index index.html;
    resolver 169.254.169.253 valid=30s ipv6=off;
    set $api_upstream YOUR_INTERNAL_ALB_DNS:8080;
    client_max_body_size 16k;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;
    add_header Cache-Control "no-store" always;

    location / { try_files $uri $uri/ =404; }
    location ~ ^/(api(?:/|$)|health(?:/|$)) {
        proxy_pass http://$api_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
    }
}
```

For an existing HTTPS internal listener, use `https://`, its port, `proxy_ssl_server_name on;`, `proxy_ssl_name` matching the certificate, `proxy_ssl_verify on;` and a trusted CA file. Do not disable certificate verification. The external ALB must terminate HTTPS for the app's Secure session cookie; private HTTP curls below are liveness checks only.

Enable this site and remove the Ubuntu default site if it conflicts:

```bash
sudo ln -sfn /etc/nginx/sites-available/kantin-orders /etc/nginx/sites-enabled/kantin-orders
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

A missing `/opt/kantin-orders/web` root is expected before the first release. Nginx configuration must already be valid. Use the DR region's internal ALB on standby web hosts. The app pipeline does not edit Nginx. [Nginx proxy documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

## 6. Confirm existing artifact and deployment permissions

The infrastructure owner provides a regional **versioned** S3 bucket and matching KMS key; this job does not create or configure them. Configure `deploy/targets.json` with those real values and exact instance IDs. The placeholder values deliberately prevent deployment.

The trusted Jenkins deployment role needs these operations restricted to the selected resources:

- `s3:GetBucketVersioning` on the release bucket and `s3:PutObject` on `releases/*`.
- `kms:GenerateDataKey` and `kms:Decrypt` as required for the artifact key, also permitted by its key policy.
- `ssm:SendCommand` using `AWS-RunShellScript` on the explicit app/web instances; `ssm:ListCommandInvocations` for completion status.

App/web instance roles need SSM managed-node permissions, `s3:GetObjectVersion` on the release prefix, and `kms:Decrypt` for downloads. Only app instances need runtime Secrets Manager access. No RDS or Auto Scaling permission is needed by this application's Jenkins job. Keep the infrastructure Jenkins role separate.

## 7. Configure the separate Jenkins application job

1. Prepare a trusted Linux agent labelled `aws-orders-ci`: Git, Node.js 24/npm, Python 3, AWS CLI v2, and the pinned Gitleaks/Trivy versions installed manually with `scripts/install-security-tools-ubuntu.sh`.
2. Install Jenkins Pipeline, Git, JUnit and Pipeline Input Step plugins, with their dependencies.
3. Create **Pipeline → Pipeline script from SCM → Git**. Repository URL: `https://github.com/kantinstephane10/3-Tier-app-DR-active-passive-webapp-AWS.git`.
4. Branch specifier: `*/feat/jenkins-only-app-deployment`; **Script Path: `Jenkinsfile`**. Disable shallow checkout: the secrets scan needs full history. Use your existing GitHub credential if repository checkout requires it.
5. Set `SECURITY_APPROVERS` in the Jenkinsfile to trusted Jenkins user/group IDs. Restrict permission to configure the job or change its source to trusted maintainers.
6. Provide AWS access through the agent's existing instance profile/assumed role. If you choose environment credentials instead, use Jenkins **Credentials**, not plain global environment values. Bind secret-text IDs `aws-access-key-id` and `aws-secret-access-key` as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` using the snippet below in the deployment stage. For temporary credentials also bind `AWS_SESSION_TOKEN`. Never put literal values in the Jenkinsfile or echo them.

```groovy
withCredentials([
  string(credentialsId: 'aws-access-key-id', variable: 'AWS_ACCESS_KEY_ID'),
  string(credentialsId: 'aws-secret-access-key', variable: 'AWS_SECRET_ACCESS_KEY')
]) {
  sh 'python3 scripts/deploy.py "$TARGET_REGION"'
}
```

This binding is an optional credential setup choice; the committed pipeline uses the agent role by default. DB passwords stay in runtime Secrets Manager and are never exposed to this job. [Jenkins credential binding](https://www.jenkins.io/doc/pipeline/steps/credentials-binding/).

7. Commit your non-secret inventory changes on the app branch. Run **`BUILD_ONLY`** and review tests and redacted security reports.
8. Run **`DEPLOY`**, selecting the intended region. App instances update first, then web instances. CRITICAL findings trigger a trusted manual approval with justification; LOW/MEDIUM/HIGH findings do not trigger approval. A rejected/expired approval, incomplete scanner run, failed tests or deployment error stops the job.

## 8. Verify after the first deployment

On an app host:

```bash
sudo systemctl status kantin-api.service kantin-worker.service --no-pager
curl -fsS http://127.0.0.1:8080/health/live
# Manual DB/schema readiness verification; not part of app deployment:
curl -fsS http://127.0.0.1:8080/health
sudo journalctl -u kantin-api.service -u kantin-worker.service --since '10 minutes ago' --no-pager
```

On a web host:

```bash
sudo nginx -t
curl -fsS http://127.0.0.1/health/live
curl -fsS http://127.0.0.1/release.json
```

Then open your external **HTTPS** application URL. Confirm the catalog, add an item, place a simulated order and observe fulfillment on the active region. Standby remains read-only until a separate, authorized DR procedure changes database writability and runtime settings. No failover automation is included here.

`/health/live` proves process availability, not database correctness. A successful Jenkins release does not certify DB connectivity, schema compatibility, replication health or complete business transactions. Those are verified manually above.

## Troubleshooting and release behavior

| Symptom | Check manually |
| --- | --- |
| SSM target offline or command denied | Existing instance role, SSM Agent, endpoints and scoped Jenkins permissions |
| Download fails | Existing bucket versioning, exact version access and KMS key policy |
| API cannot start | Node path, unit files, port conflict, regional secret access and environment file |
| API alive but catalog/readiness unavailable | Runtime DB password, hostname, CA, grants, schema and network path |
| Web returns 502 | Regional internal ALB DNS/listener, Nginx resolver and app target health |
| Standby checkout returns 503 | Expected while `WRITE_ENABLED=false` or DB is read-only |

Service restarts can interrupt requests. No load balancer draining or Auto Scaling action is performed. A failed host attempts to restore its previous symlink and restart its prior services; on the first release there is no previous version. Successful earlier hosts remain on the new release if a later host fails, so inspect the deployment report before retrying. Old releases remain in `/opt/kantin-orders/releases/`; plan manual cleanup outside deployment. The job does not change the database to roll back application code.
