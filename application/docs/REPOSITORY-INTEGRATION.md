# Application integration with this repository

The root Terraform code and infrastructure Jenkinsfile are preserved. `application/Jenkinsfile` is a separate application release pipeline. In Jenkins create an application job with SCM script path `application/Jenkinsfile`, label `aws-orders-ci`, and a full checkout of this repository. Its scripts run from `application/`; infrastructure remains in the repository root. Do not point the existing infrastructure job at the application Jenkinsfile.

The existing Terraform deployment serves a Python demo on port 8080 with `/health`, not this PostgreSQL-backed storefront. Before application DEPLOY, deliberately implement these prerequisites through the infrastructure workflow:

- Prepare Ubuntu app/web launch templates with Node.js/CodeDeploy or nginx/CodeDeploy, the regional runtime environment files, and artifact/Secrets Manager IAM access described in DEPLOYMENT.md. The present launch templates grant only SSM access and bootstrap a Python demo. Stop/disable `aws-demo.service` when replacing that demo.
- Align the internal ALB listener, app target group and SG ingress/egress with the supplied application configuration: internal listener 80 (or validated HTTPS 443), app target port 3000, app PORT=3000. Existing rules/listeners are 8080. Update all related SG rules together; never open app ports publicly.
- Set both target-group health checks to `/health/deploy`. The existing `/health` path does not match this application's separate deploy/readiness checks. Use `/health/ready` for writable readiness and coordinated regional recovery, not ASG replacement of standby instances.
- Create the database roles, application DB, regional app secrets, migration secret and CodeDeploy groups. The Terraform-managed RDS master secret is not a substitute for the restricted runtime application secret.
- Existing public ALBs use HTTP-only listeners with CloudFront-origin restrictions. This application guide requires regional HTTPS smoke hostnames with valid certificates and a restricted test-access rule. Add the TLS listeners/certificates and test paths, or implement an explicitly reviewed equivalent private smoke route before enabling DEPLOY.
- Update CloudFront dynamic behaviors to disable caching and forward cookies, CSRF and idempotency headers plus POST. Keep origin protection and WAF controls. CloudFront origin failover does not retry POST.
- The infrastructure pipeline's smoke test expects the old demo JSON response. Update it for the new storefront/API or use the application pipeline's database-backed smoke checks after replacement. Do not remove deployment validation merely to pass a release.

This application branch does not silently modify your networking, IAM, Terraform state or infrastructure pipeline. BUILD_ONLY and local preview work immediately; AWS DEPLOY requires the integration above. Preserve the latest infrastructure rollout and local state while applying those reviewed changes.
