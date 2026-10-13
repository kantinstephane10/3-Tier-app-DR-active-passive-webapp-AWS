#!/usr/bin/env bash
set -euo pipefail
systemctl enable nginx
if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
