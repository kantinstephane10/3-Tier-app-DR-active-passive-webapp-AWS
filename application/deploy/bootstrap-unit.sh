#!/usr/bin/env bash
set -euo pipefail
# Install via the reviewed launch template/AMI on every ASG instance.
TIER=${1:?app or web}
REGION=${2:?AWS region}
PARAMETER=${3:?Release parameter}
[[ "$TIER" == app || "$TIER" == web ]] || exit 1
[[ "$REGION" == us-east-1 || "$REGION" == us-west-2 ]] || exit 1
[[ "$PARAMETER" =~ ^/[a-zA-Z0-9/_-]+$ ]] || exit 1
cat > /etc/systemd/system/kantin-bootstrap.service <<EOF
[Unit]
Description=Bootstrap the current Jenkins-published $TIER release
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/kantin-bootstrap $TIER $REGION $PARAMETER
TimeoutStartSec=20min
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable kantin-bootstrap.service
systemctl start --no-block kantin-bootstrap.service
