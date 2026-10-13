#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
TIER=${1:?app or web}
BUCKET=${2:?Artifact bucket}
KEY=${3:?Artifact key}
VERSION=${4:?S3 version}
DIGEST=${5:?SHA-256}
RELEASE=${6:?Release ID}
[[ "$TIER" == app || "$TIER" == web ]] || exit 1
[[ "$BUCKET" =~ ^[a-z0-9.-]{3,63}$ && "$KEY" =~ ^[a-zA-Z0-9/_-]+\.zip$ ]] || exit 1
[[ "$VERSION" =~ ^[a-zA-Z0-9._-]+$ && "$DIGEST" =~ ^[a-f0-9]{64}$ && "$RELEASE" =~ ^[a-zA-Z0-9-]{1,100}$ ]] || exit 1
[[ "$RELEASE" != -* ]] || exit 1
exec 9>"/var/lock/kantin-orders-$TIER.lock"
flock -w 300 9
source "/etc/kantin-orders/$TIER.env"
export AWS_REGION AWS_DEFAULT_REGION="${AWS_REGION:?Set region in the runtime env file}"
release_tmp=$(mktemp -d)
CURRENT=/opt/kantin-orders/application
[[ "$TIER" == web ]] && CURRENT=/opt/kantin-orders/web
if [[ -e "$CURRENT" && ! -L "$CURRENT" ]]; then
  echo 'Current application path must be a symlink; convert any earlier directory-based deployment first.' >&2
  rm -rf "$release_tmp"
  exit 1
fi
PREVIOUS=$(readlink "$CURRENT" || true)
CHANGED=false
rollback_local() {
  if [[ "$CHANGED" == true ]]; then
    if [[ -n "$PREVIOUS" ]]; then
      ln -sfn "$PREVIOUS" "$CURRENT.rollback"
      mv -Tf "$CURRENT.rollback" "$CURRENT"
    else rm -f "$CURRENT"; fi
    if [[ "$TIER" == app ]]; then
      systemctl stop kantin-api.service kantin-worker.service || true
      if [[ -n "$PREVIOUS" ]]; then systemctl restart kantin-api.service kantin-worker.service || true; fi
    else
      systemctl restart nginx || true
    fi
  fi
}
finish() { code=$?; trap - EXIT; if [[ "$code" != 0 ]]; then rollback_local; fi; rm -rf "$release_tmp"; exit "$code"; }
trap finish EXIT
aws s3api get-object --bucket "$BUCKET" --key "$KEY" --version-id "$VERSION" "$release_tmp/release.zip" >/dev/null
printf '%s  %s\n' "$DIGEST" "$release_tmp/release.zip" | sha256sum -c -
unzip -q "$release_tmp/release.zip" -d "$release_tmp/extracted"
PAYLOAD="$release_tmp/extracted/application"
[[ "$TIER" == web ]] && PAYLOAD="$release_tmp/extracted/public"
python3 - "$PAYLOAD/release.json" "$RELEASE" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['release'] == sys.argv[2], 'Release metadata mismatch'
PY
DEST="/opt/kantin-orders/releases/$TIER/$RELEASE"
install -d -m 0755 /opt/kantin-orders "/opt/kantin-orders/releases/$TIER"
# The archive has an immutable S3 version/hash; keep installed versions for rollback.
if [[ -d "$DEST" ]]; then
  [[ -f "$DEST/.archive.sha256" && $(cat "$DEST/.archive.sha256") == "$DIGEST" ]] || { echo 'Existing release ID has different or unverified contents.' >&2; exit 1; }
else
  mv "$PAYLOAD" "$DEST"
  chown -R root:root "$DEST"
  find "$DEST" -type d -exec chmod 0755 {} +
  find "$DEST" -type f -exec chmod 0644 {} +
  printf '%s\n' "$DIGEST" > "$DEST/.archive.sha256"
fi
CHANGED=true
ln -sfn "$DEST" "$CURRENT.next"
mv -Tf "$CURRENT.next" "$CURRENT"
if [[ "$TIER" == app ]]; then
  systemctl restart kantin-api.service kantin-worker.service
  PORT=${PORT:-8080}
  [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || exit 1
  HEALTH="http://127.0.0.1:$PORT/health/live"
else
  nginx -t
  systemctl restart nginx
  HEALTH=http://127.0.0.1/health/live
fi
for attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 3 "$HEALTH" -o "$release_tmp/health.json"; then
    if python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["release"] == sys.argv[2]' "$CURRENT/release.json" "$RELEASE"; then
      if [[ "$TIER" != app ]] || { systemctl is-active --quiet kantin-api.service kantin-worker.service && python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["release"] == sys.argv[2]' "$release_tmp/health.json" "$RELEASE"; }; then
        echo "Installed $TIER release $RELEASE"
        exit 0
      fi
    fi
  fi
  sleep 3
done
echo 'Release health validation failed; restoring the previous local version.' >&2
exit 1
