#!/usr/bin/env bash
set -euo pipefail
set +x
chown -R root:root /opt/kantin-orders/application
chmod -R go-w /opt/kantin-orders/application
install -m 0644 /opt/kantin-orders/application/deploy/kantin-api.service /etc/systemd/system/kantin-api.service
install -m 0644 /opt/kantin-orders/application/deploy/kantin-worker.service /etc/systemd/system/kantin-worker.service
systemctl daemon-reload
# Migrations are run once, before this rollout, by the pipeline's VPC migration runner.
# Standby instances never run schema migrations.
