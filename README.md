# Kantin Orders — application deployment

Node.js 24 storefront and API by **Kantin Tongue**, with a PostgreSQL-backed simulated fulfillment worker. No real payments or shipping.

This branch contains application source, Jenkins CI/CD, release scripts and manual server readiness instructions. Infrastructure deployment remains in the separate Jenkins workflow on `main`. This branch does not provision databases, run schema migrations, configure load balancers, change Auto Scaling groups or create AWS resources.

## Start here

1. Follow [DB, app server and web server readiness](docs/SERVER-READINESS.md) once, outside this application pipeline.
2. Replace the existing bucket, KMS key and exact EC2 instance IDs in `deploy/targets.json` for each region you use.
3. Configure a separate Jenkins Pipeline from SCM for `*/feat/jenkins-only-app-deployment`, script path **`Jenkinsfile`**, with full Git history and an agent labelled `aws-orders-ci`.
4. Run `BUILD_ONLY`. Review application tests and security reports.
5. Run `DEPLOY` for the selected region. Only CRITICAL findings require trusted approval with a written justification. LOW/MEDIUM/HIGH findings are reported and continue. Secret findings and UNKNOWN severity count as CRITICAL; incomplete scans and test/tool failures block deployment.

The app pipeline uploads versioned release archives to an existing S3 bucket and uses SSM on the supplied EC2 IDs. It deploys app instances first, then web instances, switches the application symlink, restarts existing services and checks `/health/live`. Deployment does not connect to PostgreSQL. Runtime application requests and the worker use the separately prepared database.

## Application and validation

- `src/`: API, signed guest sessions, CSRF protection, server-side pricing, idempotent orders and worker.
- `public/`: storefront with Kantin Tongue attribution.
- `deploy/`: target inventory, sample runtime environment and reference systemd units for manual installation.
- `scripts/`: application packaging, security reporting and direct-instance release installation.
- `test/`: application and deployment tests without a running database or AWS account.

```bash
npm ci --ignore-scripts
npm run check
npm test
python3 -m unittest discover -s test -p 'test_*.py' -v
npm run bundle
```

Security tools: Gitleaks 8.30.1, Trivy 0.75.0 and npm audit. `scripts/install-security-tools-ubuntu.sh` is a manual Jenkins-agent preparation helper, not a deployment stage. Never put AWS keys, database passwords or session secrets in Git. Production runtime reads its secret from Secrets Manager through the app instance role.

Existing app and Nginx processes restart during deployment. A failed host attempts to restore its previous local release; already-successful hosts are not globally rolled back. See the guide for first-release prerequisites, standby settings and troubleshooting. Live AWS deployment requires your actual inventory and configured Jenkins environment.
