#!/usr/bin/env bash
set -euo pipefail
# Launch template/user-data preparation: Ubuntu 24.04 amd64, app|web|runner.
ROLE=${1:?Usage: provision-ubuntu.sh app|web|runner AWS_REGION}
REGION=${2:?AWS region required}
[[ "$ROLE" == app || "$ROLE" == web || "$ROLE" == runner ]] || exit 1
[[ "$REGION" == us-east-1 || "$REGION" == us-west-2 ]] || exit 1
[[ $(uname -m) == x86_64 ]] || exit 1
apt-get update
apt-get install -y ca-certificates curl unzip ruby
install -d -m 0755 /etc/kantin-orders
if [[ "$ROLE" == app || "$ROLE" == runner ]]; then
  id kantin-orders >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin kantin-orders
  NODE_VERSION=24.19.0
  node_tmp=$(mktemp -d)
  trap 'rm -rf "$node_tmp"' EXIT
  curl --fail --location --retry 3 "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" -o "$node_tmp/node.tar.xz"
  curl --fail --location --retry 3 "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" -o "$node_tmp/checksums"
  awk -v filename="node-v$NODE_VERSION-linux-x64.tar.xz" '$2 == filename { print $1 "  node.tar.xz" }' "$node_tmp/checksums" > "$node_tmp/check.sha256"
  test -s "$node_tmp/check.sha256"
  (cd "$node_tmp" && sha256sum -c check.sha256)
  tar -xJf "$node_tmp/node.tar.xz" -C /usr/local --strip-components=1
  curl --fail --location --retry 3 https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /etc/kantin-orders/rds-global-bundle.pem
  chmod 0644 /etc/kantin-orders/rds-global-bundle.pem
fi
if [[ "$ROLE" == web ]]; then apt-get install -y nginx; fi
if [[ "$ROLE" == runner ]]; then
  # Runner needs SSM agent and AWS CLI v2, provisioned in its AMI/user-data separately.
  command -v aws >/dev/null
else
  code_tmp=$(mktemp -d)
  curl --fail --location --retry 3 "https://aws-codedeploy-$REGION.s3.$REGION.amazonaws.com/latest/install" -o "$code_tmp/install"
  chmod +x "$code_tmp/install"
  "$code_tmp/install" auto
  rm -rf "$code_tmp"
  systemctl enable --now codedeploy-agent
fi
