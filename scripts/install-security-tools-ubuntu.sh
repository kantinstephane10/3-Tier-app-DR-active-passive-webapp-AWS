#!/usr/bin/env bash
set -euo pipefail
# Run on the persistent Jenkins agent as root. Pinned versions; checksum verified.
[[ $(uname -m) == x86_64 ]] || { echo 'This installer requires Linux x86_64'; exit 1; }
apt-get update
apt-get install -y curl ca-certificates tar
security_tmp=$(mktemp -d)
trap 'rm -rf "$security_tmp"' EXIT
cd "$security_tmp"
curl --fail --location --retry 3 -O https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
curl --fail --location --retry 3 -O https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt
awk '$2 == "gitleaks_8.30.1_linux_x64.tar.gz" {print}' gitleaks_8.30.1_checksums.txt > gitleaks.sha256
test -s gitleaks.sha256
sha256sum -c gitleaks.sha256
tar -xzf gitleaks_8.30.1_linux_x64.tar.gz gitleaks
install -m 0755 gitleaks /usr/local/bin/gitleaks
curl --fail --location --retry 3 -O https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz
curl --fail --location --retry 3 -O https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_checksums.txt
awk '$2 == "trivy_0.75.0_Linux-64bit.tar.gz" {print}' trivy_0.75.0_checksums.txt > trivy.sha256
test -s trivy.sha256
sha256sum -c trivy.sha256
tar -xzf trivy_0.75.0_Linux-64bit.tar.gz trivy
install -m 0755 trivy /usr/local/bin/trivy
gitleaks version
trivy --version
