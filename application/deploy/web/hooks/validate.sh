#!/usr/bin/env bash
set -euo pipefail
curl --fail --silent --max-time 5 http://127.0.0.1/ >/dev/null
for attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 5 http://127.0.0.1/health/deploy >/dev/null; then exit 0; fi
  sleep 3
done
exit 1
