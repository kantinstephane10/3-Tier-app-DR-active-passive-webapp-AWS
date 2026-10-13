#!/usr/bin/env bash
set -euo pipefail
test -f /etc/kantin-orders/app.env
test -x /usr/local/bin/node
id kantin-orders >/dev/null
for unit in kantin-api.service kantin-worker.service; do
  if [[ $(systemctl show "$unit" -p LoadState --value) != not-found ]]; then systemctl stop "$unit"; fi
done
rm -rf /opt/kantin-orders/application
install -d -m 0755 /opt/kantin-orders/application
