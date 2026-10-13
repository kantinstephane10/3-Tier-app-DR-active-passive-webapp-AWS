pipeline {
  agent { label 'aws-orders-ci' }
  options {
    disableConcurrentBuilds()
    timestamps()
    timeout(time: 120, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }
  parameters {
    choice(name: 'ACTION', choices: ['BUILD_ONLY', 'DEPLOY'], description: 'First run builds and scans; DEPLOY releases to existing EC2 tiers.')
    choice(name: 'TARGET_REGION', choices: ['us-east-1', 'us-west-2'], description: 'Select the region containing your existing EC2 instances.')
  }
  environment {
    SECURITY_APPROVERS = 'security-approvers' // Replace with trusted Jenkins group/user IDs.
    AWS_PAGER = ''
    AWS_DEFAULT_REGION = "${params.TARGET_REGION}"
    NPM_CONFIG_FUND = 'false'
  }
  stages {
    stage('Checkout') {
      steps {
        deleteDir()
        checkout scm
        script { env.RELEASE_ID = "${env.GIT_COMMIT}-${env.BUILD_NUMBER}" }
      }
    }
    stage('Toolchain') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
test "$(node -p 'process.versions.node.split(".")[0]')" = 24
gitleaks version | grep -Fx '8.30.1'
trivy --version | grep -Fx 'Version: 0.75.0'
python3 --version
aws --version
'''
      }
    }
    stage('Install, syntax and application tests') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
npm ci --ignore-scripts
npm run check
python3 -m unittest discover -s test -p 'test_*.py' -v
mkdir -p reports
node --test --test-reporter=spec --test-reporter-destination=stdout --test-reporter=junit --test-reporter-destination=reports/tests.xml test/*.test.js
'''
      }
      post { always { junit testResults: 'reports/tests.xml', allowEmptyResults: true } }
    }
    stage('Security scans and release bundles') {
      steps {
        sh '''#!/usr/bin/env bash
set -euo pipefail
npm ci --omit=dev --ignore-scripts
python3 scripts/security.py
npm run bundle
'''
        script {
          env.APPROVED_MANIFEST_SHA = sh(script: 'sha256sum dist/manifest.json | cut -d " " -f1', returnStdout: true).trim()
        }
      }
    }
    stage('Critical-only security approval') {
      when { expression { params.ACTION == 'DEPLOY' } }
      steps {
        script {
          archiveArtifacts artifacts: 'reports/security/*.json', fingerprint: true
          def critical = sh(script: 'python3 -c "import json; print(json.load(open(\'reports/security/summary.json\'))[\'criticalCount\'])"', returnStdout: true).trim().toInteger()
          if (critical > 0) {
            def approval
            timeout(time: 30, unit: 'MINUTES') {
              approval = input(id: 'criticalRiskAcceptance',
                message: "${critical} CRITICAL findings. Review this build's reports before deploying ${env.RELEASE_ID} to ${params.TARGET_REGION}.",
                ok: 'Accept risk and deploy', submitter: env.SECURITY_APPROVERS,
                submitterParameter: 'APPROVER',
                parameters: [text(name: 'JUSTIFICATION', defaultValue: '', description: 'Required reason. Do not include secrets.')])
            }
            if (!approval.JUSTIFICATION?.trim()) { error('Risk acceptance requires a reason.') }
            writeFile file: 'reports/security/approval.json', text: groovy.json.JsonOutput.toJson([
              approver: approval.APPROVER, justification: approval.JUSTIFICATION,
              build: env.BUILD_URL, release: env.RELEASE_ID, region: params.TARGET_REGION,
              criticalCount: critical, manifestSha256: env.APPROVED_MANIFEST_SHA,
              time: new Date().format("yyyy-MM-dd'T'HH:mm:ssXXX", TimeZone.getTimeZone('UTC'))])
          } else { echo 'No CRITICAL findings: release continues automatically.' }
        }
      }
    }
    stage('Deploy application to existing EC2 instances') {
      when { expression { params.ACTION == 'DEPLOY' } }
      steps {
        // AWS CLI uses the trusted agent's instance profile/assumed role. No keys in Git.
        sh 'python3 scripts/deploy.py "$TARGET_REGION"'
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'reports/security/*.json,reports/deployment.json,dist/manifest.json', allowEmptyArchive: true, fingerprint: true
    }
    success { archiveArtifacts artifacts: 'dist/app.zip,dist/web.zip', fingerprint: true }
  }
}
