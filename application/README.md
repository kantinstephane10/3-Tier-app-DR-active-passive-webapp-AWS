# Kantin Supply — Node.js application for Kantin Tongue's AWS architecture

A working portfolio storefront and order-processing application for the attached EC2 three-tier, two-region diagram. This is application and delivery code; it does not create the VPCs, ASGs, load balancers, RDS databases, backup vaults or CloudFront distribution.

## What runs where

| Diagram component | Application implementation |
|---|---|
| CloudFront + WAF + Route 53 | HTTPS entry point; forwards API/session traffic without caching |
| Public regional load balancer | HTTPS listener; routes to the private web ASG |
| Web EC2 ASG | Nginx serves `public/` and proxies `/api/` and health paths |
| Internal load balancer | Routes from web EC2 to private app EC2 on port 3000 |
| App EC2 ASG | Node.js 24 API and a separate systemd worker per instance |
| RDS primary/Multi-AZ standby | PostgreSQL 17 database; use the normal RDS writer endpoint |
| Cross-region RDS read replica | Read-only database until explicitly promoted |
| AWS Backup | Infrastructure backup and restore; not implemented by application code |
| Jenkins + CodeDeploy | Tests, security scans, migrations, rolling app/web releases |

The worker uses a transactional PostgreSQL job table, avoiding additional infrastructure beyond your diagram. Multiple workers coordinate with `FOR UPDATE SKIP LOCKED`. The database transaction contains both the order and its job; fulfillment also commits atomically. No payment provider, shipping, email service or SQS queue is required.

## Features

- Responsive storefront, search, category filters, bag and guest order history.
- Prices come from PostgreSQL; the client cannot choose its own price.
- Idempotency keys prevent duplicate orders when checkout is retried.
- Guest sessions use signed, expiring HttpOnly cookies; mutation requires a CSRF token.
- API error responses and structured logs omit passwords, cookies and order payloads.
- Production reads credentials using the EC2 instance role and AWS Secrets Manager.
- Verified TLS to RDS, with the AWS RDS CA bundle.
- Standby mode and the database's read-only state prevent accepting new orders.
- Deploy health is separate from writable readiness so standby releases can be verified.

This is a portfolio application. Checkout and fulfillment are simulations; there are no real payments or deliveries. Guest sessions are not customer accounts, and losing the cookie loses access to that browser's order history. Add a real identity provider and authorization model before using real customers or personal data.

## Run immediately without Docker

Install Node.js 24, then from this directory:

```bash
npm ci --ignore-scripts
npm test
npm run preview
```

Open http://127.0.0.1:3000. The preview uses an embedded PostgreSQL engine (PGlite) with a temporary database. Its data and sessions reset when the preview restarts. It is a development convenience and is never included as a production dependency.

## Run with PostgreSQL locally

Use an existing PostgreSQL 17 database, or use the included local-only Compose database:

```bash
docker compose up -d --wait
npm ci --ignore-scripts
cp .env.example .env
```

Replace SESSION_SECRET in `.env` with at least 32 random characters. Then, in three terminal commands/sessions:

```bash
node --env-file=.env src/migrate.js
node --env-file=.env src/server.js
node --env-file=.env src/worker.js
```

Open http://127.0.0.1:3000. Never use the local example password or disable database TLS on EC2. `.env` files and private keys are excluded from Git and release bundles.

## Prepare AWS and deploy

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) in order. It covers RDS roles, regional secrets, EC2 preparation, security groups, both CodeDeploy groups, artifact buckets, the migration runner and Jenkins configuration. Configure `deploy/regions.json` with your actual AWS resource names; its placeholders intentionally prevent deployment.

Jenkins first runs BUILD_ONLY. A DEPLOY build performs:

1. Full Git checkout and tool/version checks.
2. Dependency installation, syntax checks and delivery-policy tests.
3. Integration tests against an isolated real PostgreSQL 17 container.
4. Production dependency installation and Gitleaks, Trivy and npm audit scans.
5. App/web CodeDeploy ZIP bundles and a SHA-256 manifest.
6. Approval only for CRITICAL findings; LOW/MEDIUM/HIGH findings continue.
7. Hash verification, encrypted/versioned S3 upload and active-region schema migration.
8. App deployment, then web deployment, then HTTPS checkout/worker smoke tests.

Jenkins runtime, Docker integration tests, RDS connectivity and actual AWS deployments still need to run in your environment. No AWS resources were created during code generation. See `VALIDATION.json` for checks actually completed here.

## Regional recovery

Follow [docs/RECOVERY.md](docs/RECOVERY.md). RDS Multi-AZ standby is not a second readable application database. The cross-region replica is asynchronous, and promotion does not automatically switch application traffic. CloudFront origin failover only retries GET/HEAD/OPTIONS; it does not provide POST checkout failover. Keep one writable region and coordinate fencing, database promotion, application activation and routing changes.

## Main files

| Path | Purpose |
|---|---|
| src/http.js | HTTP API, health, signed guest sessions and CSRF validation |
| src/orders.js | Order transactions, idempotency and fulfillment jobs |
| src/config.js | Secrets Manager and verified PostgreSQL TLS |
| db/001-initial.sql | Schema and six sample products |
| public/ | Storefront HTML, CSS and browser code |
| Jenkinsfile | Application CI/CD and critical-only approval |
| deploy/app/, deploy/web/ | EC2 CodeDeploy AppSpec files and hooks |
| scripts/deploy.py | Immutable S3 revisions, migrations, rollout and smoke checks |
| scripts/security.py | Validated scanner results and sanitized security reports |

The infrastructure Terraform pipeline remains a separate workflow. This application project adds no Terraform backend and does not change your local-state preference.
