#!/usr/bin/env bash
set -euo pipefail
for unit in kantin-api.service kantin-worker.service; do
  if [[ $(systemctl show "$unit" -p LoadState --value) != not-found ]]; then systemctl stop "$unit"; fi
done
