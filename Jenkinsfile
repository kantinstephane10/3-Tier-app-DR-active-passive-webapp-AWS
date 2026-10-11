pipeline {
  agent { label 'terraform-local' }
  options {
    disableConcurrentBuilds()
    timestamps()
    timeout(time: 150, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '15'))
    skipDefaultCheckout(true)
  }
  parameters {
    choice(name: 'ROLLOUT', choices: ['foundation', 'primary', 'dr', 'edge'], description: 'Cumulative stage. Keep the latest deployed stage.')
    choice(name: 'ACTION', choices: ['PLAN', 'APPLY'], description: 'APPLY applies this build’s saved plan.')
  }
  environment {
    REPO_URL = 'https://github.com/kantinstephane10/3-Tier-app-DR-active-passive-webapp-AWS.git'
    REPO_BRANCH = 'main'
    REPO_CREDENTIALS = '' // Jenkins credential ID for a private repository; leave empty while the repository is public.
    SECURITY_APPROVERS = 'security-approvers' // Replace with your trusted Jenkins group/user IDs.
    AWS_ACCESS_KEY_ID = credentials('aws-access-key-id')
    AWS_SECRET_ACCESS_KEY = credentials('aws-secret-access-key')
    AWS_EC2_METADATA_DISABLED = 'true'
    AWS_PAGER = ''
    TF_IN_AUTOMATION = 'true'
    TF_INPUT = 'false'
    TF_WORKSPACE = 'default'
    STATE_DIR = '/var/lib/jenkins/terraform-state/kt-aws-lab'
  }
  stages {
    stage('Checkout') {
      steps {
        // Full clone: Gitleaks scans the complete Git history.
        checkout([$class: 'GitSCM',
          branches: [[name: "*/${env.REPO_BRANCH}"]],
          userRemoteConfigs: [[url: env.REPO_URL, credentialsId: env.REPO_CREDENTIALS ?: null]],
          extensions: [[$class: 'CloneOption', shallow: false, noTags: true], [$class: 'CleanBeforeCheckout']]])
        sh 'git log -1 --format="Deploying commit %H: %s"'
      }
    }
    stage('Security: source and secrets') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
set +x
gitleaks version | grep -Fx '8.30.1'
trivy --version | grep -Fx 'Version: 0.75.0'
python3 scripts/security-scan.py source
python3 scripts/security-report.py
'''
      }
    }
    stage('Check persistent local state') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
set +x
test -d "$STATE_DIR"
test -w "$STATE_DIR"
if [[ -f "$STATE_DIR/state-created" && ! -s "$STATE_DIR/infrastructure.tfstate" ]]; then
  echo 'The state file is missing after an earlier deployment. Restore it before running Terraform.' >&2
  exit 1
fi
terraform version
'''
      }
    }
    stage('AWS identity and configuration') {
      steps {
        withCredentials([file(credentialsId: 'aws-lab-tfvars', variable: 'TFVARS_FILE')]) {
          sh '''#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
cp "$TFVARS_FILE" environments/lab/config.tfvars
caller_account=$(aws sts get-caller-identity --query Account --output text)
expected_account=$(sed -nE 's/^[[:space:]]*account_id[[:space:]]*=[[:space:]]*"([0-9]{12})".*/\\1/p' environments/lab/config.tfvars)
if [[ "$caller_account" != "$expected_account" ]]; then
  echo 'The Jenkins AWS keys belong to a different account than config.tfvars account_id.' >&2
  exit 1
fi
echo 'AWS credentials match the configured account.'
'''
        }
      }
    }
    stage('Format, initialize and test') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
terraform fmt -check -recursive
terraform -chdir=environments/lab init -input=false
terraform -chdir=environments/lab validate
terraform -chdir=environments/lab test
python3 -m unittest discover -s tests
'''
      }
    }
    stage('Plan') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
umask 077
terraform -chdir=environments/lab plan -input=false -lock-timeout=5m -var-file=config.tfvars -var="stage=$ROLLOUT" -out=deployment.tfplan
terraform -chdir=environments/lab show -json deployment.tfplan > environments/lab/plan.json
python3 scripts/check-plan.py environments/lab/plan.json
'''
      }
    }
    stage('Security: resolved Terraform plan') {
      steps {
        sh 'python3 scripts/security-scan.py plan && python3 scripts/security-report.py'
        script {
          env.APPROVED_PLAN_SHA = sh(script: 'sha256sum environments/lab/deployment.tfplan | cut -d " " -f1', returnStdout: true).trim()
        }
      }
    }
    stage('Critical security approval') {
      when { expression { params.ACTION == 'APPLY' } }
      steps {
        script {
          archiveArtifacts artifacts: 'reports/security/*.json', fingerprint: true
          def critical = sh(script: 'python3 -c "import json; print(json.load(open(\'reports/security/summary.json\'))[\'critical_count\'])"', returnStdout: true).trim().toInteger()
          if (critical > 0) {
            def approval
            timeout(time: 30, unit: 'MINUTES') {
              approval = input(id: 'criticalSecurityOverride',
                message: "${critical} CRITICAL security findings. Review this build's Security Scan Report tab before accepting the risk for ${params.ACTION}/${params.ROLLOUT}.",
                ok: 'Accept risk and continue', submitter: env.SECURITY_APPROVERS,
                submitterParameter: 'APPROVER',
                parameters: [text(name: 'JUSTIFICATION', defaultValue: '', description: 'Required risk acceptance reason. Do not enter secrets.')])
            }
            if (!approval.JUSTIFICATION?.trim()) { error('A risk acceptance reason is required.') }
            writeFile file: 'reports/security/approval.json', text: groovy.json.JsonOutput.toJson([
              approver: approval.APPROVER, justification: approval.JUSTIFICATION,
              build: env.BUILD_URL, action: params.ACTION, rollout: params.ROLLOUT,
              criticalCount: critical, planSha256: env.APPROVED_PLAN_SHA,
              commit: sh(script: 'git rev-parse HEAD', returnStdout: true).trim(),
              approvedAt: new Date().format("yyyy-MM-dd'T'HH:mm:ssXXX", TimeZone.getTimeZone('UTC'))])
          } else {
            echo 'No CRITICAL findings: deployment continues automatically.'
          }
        }
      }
    }
    stage('Apply saved plan') {
      when { expression { params.ACTION == 'APPLY' } }
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
umask 077
echo "$APPROVED_PLAN_SHA  environments/lab/deployment.tfplan" | sha256sum -c -
terraform -chdir=environments/lab apply -input=false -lock-timeout=5m deployment.tfplan
'''
      }
    }
    stage('Smoke test') {
      when { expression { params.ACTION == 'APPLY' && params.ROLLOUT != 'foundation' } }
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
terraform -chdir=environments/lab output -json > environments/lab/outputs.json
python3 scripts/smoke-test.py environments/lab/outputs.json
'''
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'reports/security/*.json, reports/security/index.html', allowEmptyArchive: true, fingerprint: true
      script {
        // Adds a "Security Scan Report" link to the build page (HTML Publisher plugin).
        if (fileExists('reports/security/index.html')) {
          publishHTML(target: [reportName: 'Security Scan Report', reportDir: 'reports/security', reportFiles: 'index.html',
            keepAll: true, alwaysLinkToLastBuild: true, allowMissing: true])
        }
      }
      script {
        if (fileExists('scripts/backup-local-state.py')) {
          sh 'python3 scripts/backup-local-state.py "$STATE_DIR"'
        }
      }
      sh 'rm -f environments/lab/config.tfvars environments/lab/deployment.tfplan environments/lab/plan.json environments/lab/outputs.json'
    }
  }
}
