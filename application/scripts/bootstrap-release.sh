#!/usr/bin/env bash
set -euo pipefail
set +x
TIER=${1:?app or web}
REGION=${2:?AWS region}
PARAMETER=${3:?Release parameter name}
[[ "$TIER" == app || "$TIER" == web ]] || exit 1
[[ "$REGION" == us-east-1 || "$REGION" == us-west-2 ]] || exit 1
[[ "$PARAMETER" =~ ^/[a-zA-Z0-9/_-]+$ ]] || exit 1
bootstrap_tmp=$(mktemp)
trap 'rm -f "$bootstrap_tmp"' EXIT
# First launch can precede the first Jenkins publication. Never silently use a demo version.
for attempt in $(seq 1 60); do
  if aws --region "$REGION" ssm get-parameter --name "$PARAMETER" --query Parameter.Value --output text > "$bootstrap_tmp" 2>/dev/null; then
    python3 - "$bootstrap_tmp" "$TIER" <<'PY'
import json, subprocess, sys
revision = json.load(open(sys.argv[1]))
subprocess.run(['/usr/local/bin/kantin-release', sys.argv[2],
                revision['bucket'], revision['key'], revision['version'],
                revision['sha256'], revision['release']], check=True)
PY
    exit 0
  fi
  sleep 10
done
echo 'No published release is available. Publish with Jenkins before accepting traffic.' >&2
exit 1
