#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y ca-certificates curl unzip git python3 snapd
# AWS CLI v2 from the snap AWS publishes.
sudo snap install aws-cli --classic
TASK_TMP=$(mktemp -d)
trap 'rm -rf "$TASK_TMP"' EXIT
TASK_VERSION=1.12.2
TASK_ZIP="terraform_${TASK_VERSION}_linux_amd64.zip"
cd "$TASK_TMP"
curl -fsSLO "https://releases.hashicorp.com/terraform/${TASK_VERSION}/${TASK_ZIP}"
curl -fsSLO "https://releases.hashicorp.com/terraform/${TASK_VERSION}/terraform_${TASK_VERSION}_SHA256SUMS"
grep "$TASK_ZIP" "terraform_${TASK_VERSION}_SHA256SUMS" | sha256sum -c -
unzip -q "$TASK_ZIP" terraform
sudo install -m 0755 terraform /usr/local/bin/terraform
terraform version
aws --version
