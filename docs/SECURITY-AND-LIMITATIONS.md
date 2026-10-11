# Security design and limitations

## Controls in place

- **Edge:** AWS WAF in front of CloudFront, with managed common, known-bad-inputs and IP-reputation rules and a 2,000 requests / 5 minutes per-IP rate limit. HTTP viewers are redirected to HTTPS.
- **Origin lock-down:** the public ALB security group accepts only CloudFront's origin-facing prefix list. The listener returns 403 unless the request carries the secret `X-Origin-Verify` header, which Terraform generates and CloudFront adds. Other CloudFront distributions therefore cannot use the ALB as their origin.
- **Network tiers:** each tier's security group admits only the tier in front of it (CloudFront → ALB → web → internal ALB → app → RDS). The database subnets have no internet route. The bastion has no inbound rules and is reached through SSM Session Manager.
- **Instances:** IMDSv2 required, encrypted gp3 volumes, no public IPs except the bastion's (needed for its outbound SSM connection).
- **Database:** encrypted storage in both regions, not publicly accessible, master password generated and stored by RDS in Secrets Manager, IAM authentication enabled, deletion protection, 7-day backups, PostgreSQL logs exported to CloudWatch.
- **Pipeline identity:** a dedicated IAM user with PowerUserAccess plus IAM rights limited to `kt-lab-*` roles and three named managed policies. Providers pin `allowed_account_ids`, and the pipeline checks the caller's account before planning.
- **State:** local on one agent, mode 0600, outside the workspace, snapshotted after each build.

## Known limitations

- **Outbound internet (Trivy AWS-0104, CRITICAL):** web, app and bastion allow TCP 80/443 to anywhere through NAT. To remove this you would need a custom AMI with nginx and the app preinstalled, plus VPC interface endpoints for `ssm`, `ssmmessages` and `ec2messages` in each region (an hourly charge per endpoint per AZ). The egress rules could then be restricted to the VPC CIDR.
- **HTTP between CloudFront and the ALBs:** the origins are plain HTTP, like the Azure version's Front Door → Application Gateway hop, and the secret header travels in that request. For end-to-end TLS, add an ACM certificate and an HTTPS listener per region, with a DNS name for each ALB, and switch `origin_protocol_policy` to `https-only`.
- **No VPC flow logs, ALB access logs or CloudFront logs** (Trivy AWS-0178 and similar). Add them with an S3 log bucket or CloudWatch Logs when you need traffic auditing.
- **CloudFront failover is per request** and only covers GET/HEAD/OPTIONS. See [FAILOVER.md](FAILOVER.md).
- **Long-lived access keys:** the AWS equivalent of the Azure client secret. If the agent runs in AWS, prefer an instance profile. Otherwise rotate the key regularly and keep it only in Jenkins credentials.
- **Demo application:** the app tier returns JSON and never connects to the database. Replace it with your real application before testing database failover.
