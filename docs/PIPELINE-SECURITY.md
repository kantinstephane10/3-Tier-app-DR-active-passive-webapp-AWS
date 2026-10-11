# Security checks and critical-only approval

Owner: Kantin Tongue.

Install the scanners once on the persistent Jenkins agent:

```bash
sudo bash scripts/install-security-tools-ubuntu.sh
```

The installer pins Gitleaks 8.30.1 and Trivy 0.75.0 and verifies their release checksums. The pipeline stops if the installed versions differ.

In Jenkins, install the **Pipeline: Input Step** and **HTML Publisher** plugins. Replace `SECURITY_APPROVERS = 'security-approvers'` in the Jenkinsfile with an existing Jenkins group or a comma-separated list of trusted user IDs. Jenkins administrators can also approve. Protect the `main` branch, the Jenkinsfile, the scanner configuration and the agent from untrusted edits.

| Result | Behavior |
| --- | --- |
| LOW / MEDIUM / HIGH | Shown in the report; the build continues |
| CRITICAL | APPLY pauses until an authorized approver accepts the risk |
| Detected secret | Treated as CRITICAL |
| Unrated misconfiguration | Treated as CRITICAL |
| Missing tool, wrong version, invalid output, scanner error, shallow history | Build fails; no waiver possible |
| Terraform validation or test failure, deletion guard, plan hash mismatch, apply failure | Build fails; no waiver possible |

## What runs

- **Gitleaks** scans the full Git history and the working tree, with secrets redacted.
- **Trivy** scans the Terraform source, then the resolved Terraform plan (after variables and module outputs are known).

PLAN runs every scan and publishes the report without waiting for approval. APPLY combines the source and plan findings and asks for approval only when CRITICAL findings exist. Rejection, cancellation, a blank justification or the 30-minute timeout stops the build. Every build scans again and needs its own approval; there is no global bypass.

## Reviewing the report in Jenkins

Open the build and click **Security Scan Report**. The page shows the counts per severity and a table with one row per finding:

| Column | Meaning |
|---|---|
| Severity | CRITICAL, HIGH, MEDIUM or LOW, colour coded |
| Phase | `source` (repository files) or `plan` (resolved Terraform plan) |
| Tool | trivy or gitleaks |
| Check | Rule ID, linked to the rule's documentation |
| Title | What the rule checks |
| File / Line | Where the finding is |
| Resource | Terraform resource or module (for Gitleaks: the commit) |
| Fix | The scanner's suggested resolution |

The same table is printed in Console Output after each scan. The raw JSON (`source.json`, `plan.json`, `summary.json`) and `index.html` are archived as build artifacts. When someone accepts a risk, `approval.json` records the approver, justification, commit, build, rollout, timestamp and saved-plan SHA-256. Do not put secrets into the justification.

The report contains rule metadata and locations only. Code snippets, matched secret values and Terraform values are never copied into it. Raw scanner output lives in a private temporary directory that is deleted after each scan.

If the report page looks unstyled, that is Jenkins' default Content Security Policy, which blocks stylesheets in published HTML. The page uses plain HTML table attributes, so it stays readable without changing the policy.

## Known findings

| Check | Severity | Why it exists |
|---|---|---|
| AWS-0104 (6 rules) | CRITICAL | Web, app and bastion security groups allow outbound TCP 80/443 to `0.0.0.0/0` through the NAT gateways, for Ubuntu packages and the SSM agent. |
| AWS-0178 | MEDIUM | VPC flow logs are not enabled. |
| AWS-0143 | LOW | The bootstrap attaches policies directly to the `kt-lab-jenkins` user rather than through a group. |

Approval accepts the risk for that one build; it does not fix anything. For a secret finding, revoke and rotate the credential and remove it from the repository history.

Official references:
- https://github.com/gitleaks/gitleaks
- https://trivy.dev/docs/latest/coverage/iac/terraform/
- https://plugins.jenkins.io/pipeline-input-step/
- https://plugins.jenkins.io/htmlpublisher/
