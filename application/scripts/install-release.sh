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
DEMO_WAS_ACTIVE=false
if [[ "$TIER" == app ]] && systemctl is-active --quiet aws-demo.service; then DEMO_WAS_ACTIVE=true; fi
if [[ "$TIER" == web ]]; then
  [[ ! -e /etc/nginx/conf.d/kantin-orders.conf ]] || cp -a /etc/nginx/conf.d/kantin-orders.conf "$release_tmp/nginx.before"
  [[ ! -e /etc/nginx/sites-enabled/default ]] || cp -a /etc/nginx/sites-enabled/default "$release_tmp/default.before"
fi
rollback_local() {
  if [[ "$CHANGED" == true ]]; then
    if [[ -n "$PREVIOUS" ]]; then
      ln -s "$PREVIOUS" "$CURRENT.rollback"
      mv -Tf "$CURRENT.rollback" "$CURRENT"
    else rm -f "$CURRENT"; fi
    if [[ "$TIER" == app ]]; then
      systemctl stop kantin-api.service kantin-worker.service || true
      if [[ -n "$PREVIOUS" ]]; then systemctl restart kantin-api.service kantin-worker.service || true; fi
      if [[ "$DEMO_WAS_ACTIVE" == true ]]; then systemctl start aws-demo.service || true; fi
    else
      rm -f /etc/nginx/conf.d/kantin-orders.conf
      [[ ! -f "$release_tmp/nginx.before" ]] || cp -a "$release_tmp/nginx.before" /etc/nginx/conf.d/kantin-orders.conf
      if [[ -e "$release_tmp/default.before" || -L "$release_tmp/default.before" ]]; then cp -a "$release_tmp/default.before" /etc/nginx/sites-enabled/default; fi
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
ln -s "$DEST" "$CURRENT.next"
mv -Tf "$CURRENT.next" "$CURRENT"
if [[ "$TIER" == app ]]; then
  if systemctl is-active --quiet aws-demo.service; then systemctl stop aws-demo.service; fi
  install -m 0644 "$DEST/deploy/kantin-api.service" /etc/systemd/system/kantin-api.service
  install -m 0644 "$DEST/deploy/kantin-worker.service" /etc/systemd/system/kantin-worker.service
  systemctl daemon-reload
  systemctl enable kantin-api.service kantin-worker.service
  systemctl restart kantin-api.service kantin-worker.service
  PORT=${PORT:-8080}
  [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || exit 1
  HEALTH="http://127.0.0.1:$PORT/health/deploy"
else
  /usr/local/bin/kantin-configure-web
  systemctl enable nginx
  systemctl restart nginx
  HEALTH=http://127.0.0.1/health/deploy
fi
for attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 3 "$HEALTH" >/dev/null; then
    MARKER="$HEALTH"
    [[ "$TIER" == web ]] && MARKER=http://127.0.0.1/release.json
    if curl --fail --silent --max-time 3 "$MARKER" | python3 -c 'import json,sys; assert json.load(sys.stdin)["release"] == sys.argv[1]' "$RELEASE"; then
      if [[ "$TIER" != app ]] || systemctl is-active --quiet kantin-worker.service; then
        echo "Installed $TIER release $RELEASE"
        exit 0
      fi
    fi
  fi
  sleep 3
done
echo 'Release health validation failed; restoring the previous local version.' >&2
exit 1
