# Infrastructure/app pipeline separation

The Jenkinsfile on main owns AWS infrastructure deployment and setup. The application Jenkinsfile on feat/jenkins-only-app-deployment releases application code to its existing EC2 web/app Auto Scaling groups. This branch does not modify the root Jenkinsfile, Terraform modules, provider/backend configuration or local state.

| Job | SCM branch | Script path | Responsibility |
|---|---|---|---|
| Infrastructure | main | Jenkinsfile | VPCs, ALBs, ASGs, RDS, IAM, backup, CloudFront/WAF and host/setup prerequisites |
| Application | feat/jenkins-only-app-deployment | application/Jenkinsfile | Tests, scans, critical-only approval, schema migration and Jenkins-controlled rolling release |

Run the main infrastructure job first. Its current output `regional.value` contains regional origin and ASG names, `bastions.value` contains management instance IDs, and `database.value` contains RDS endpoints and its managed master-secret ARN. Use these as the handoff when configuring `application/deploy/regions.json` and regional host configuration. Never use an app release to create a second environment or fresh Terraform state.

The application matches the repository's existing listener/target ports: web 80, internal ALB/app 8080 and PostgreSQL 5432. `/health` is a deploy-health compatibility alias, so the existing target-group checks can stay in place. `/health/ready` is separate writable readiness; a standby instance must not be replaced merely because checkout is disabled.

The current main templates bootstrap a Python demo and grant instance roles SSM access. They do not yet provision everything required by this application. The main infrastructure/setup workflow must provide the versioned artifact bucket/KMS key, protected app/migration secrets and DB roles, instance/agent permissions, runtime env files and reviewed host/bootstrap scripts described in DEPLOYMENT.md. This app pipeline checks those prerequisites and stops if they are missing; it does not create or repair IAM, networking, databases or launch templates itself.

For future ASG instances, bake the runtime scripts/settings into the main-owned AMI or launch-template setup and enable `kantin-bootstrap.service`. A manually prepared pair of instances alone is insufficient for scaling. Ensure the main-owned images/templates no longer enable the Python demo after adoption of the real application. The installer stops an active `aws-demo.service` while replacing the current first-generation app host, but the infrastructure owner must remove it from future launches.

The application's AWS operations are release-file uploads, release-pointer/lease updates, temporary ASG process suspension/restoration, target drain/registration and SSM command execution. These are application rollout operations, not infrastructure creation. The lease prevents concurrent app jobs in a region; avoid running the main infrastructure job during a rollout because it does not currently honor that app lease.

The main pipeline's original smoke test expects demo JSON at `/`. After replacing the demo with the storefront, the infrastructure owner must adjust that verification to the app's `/health` and `/api/status` paths (or the supplied app smoke checks). This branch leaves the main job unchanged as requested. CloudFront must forward API methods, cookies and CSRF/idempotency headers without caching. Root HTTP-origin protection stays in place; regional application verification runs via SSM without adding public test access or a new ALB certificate.
