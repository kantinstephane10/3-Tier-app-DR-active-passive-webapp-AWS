#!/usr/bin/env bash
set -euo pipefail
for attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:3000/health/deploy >/dev/null && systemctl is-active --quiet kantin-worker.service; then exit 0; fi
  sleep 3
done
echo 'Application health validation failed' >&2
exit 1
