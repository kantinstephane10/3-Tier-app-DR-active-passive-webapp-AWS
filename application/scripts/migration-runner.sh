#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
# Invoked on the primary VPC SSM migration runner, never a standby app instance.
BUCKET=${1:?Artifact bucket}
KEY=${2:?App artifact key}
VERSION=${3:?S3 version ID}
EXPECTED_SHA=${4:?App archive SHA-256}
[[ "$BUCKET" =~ ^[a-z0-9.-]{3,63}$ && "$KEY" =~ ^[a-zA-Z0-9/_-]+\.zip$ ]] || exit 1
[[ "$VERSION" =~ ^[a-zA-Z0-9._-]+$ && "$EXPECTED_SHA" =~ ^[a-f0-9]{64}$ ]] || exit 1
source /etc/kantin-orders/migration.env
export NODE_ENV AWS_REGION DB_SSL DB_CA_FILE MIGRATION_SECRET_ARN
export AWS_DEFAULT_REGION="$AWS_REGION"
export APP_SECRET_ARN="$MIGRATION_SECRET_ARN"
export WRITE_ENABLED=true
migration_tmp=$(mktemp -d)
trap 'rm -rf "$migration_tmp"' EXIT
aws s3api get-object --bucket "$BUCKET" --key "$KEY" --version-id "$VERSION" "$migration_tmp/app.zip" >/dev/null
printf '%s  %s\n' "$EXPECTED_SHA" "$migration_tmp/app.zip" | sha256sum -c -
unzip -q "$migration_tmp/app.zip" -d "$migration_tmp/release"
cd "$migration_tmp/release/application"
/usr/local/bin/node src/migrate.js
