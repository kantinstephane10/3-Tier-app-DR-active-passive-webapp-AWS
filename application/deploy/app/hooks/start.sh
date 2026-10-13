#!/usr/bin/env bash
set -euo pipefail
systemctl enable kantin-api.service kantin-worker.service
systemctl restart kantin-api.service kantin-worker.service
