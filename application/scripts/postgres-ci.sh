#!/usr/bin/env bash
set -euo pipefail
test_db_name="kt-orders-test-${BUILD_NUMBER:-local}-$$"
test_db_id=$(docker run -d --name "$test_db_name" -e POSTGRES_USER=orders -e POSTGRES_PASSWORD=orders -e POSTGRES_DB=orders_test -p 127.0.0.1::5432 postgres:17)
trap 'docker rm -f "$test_db_id" >/dev/null' EXIT
ready=false
for attempt in $(seq 1 30); do
  if docker exec "$test_db_id" pg_isready -U orders -d orders_test >/dev/null; then ready=true; break; fi
  sleep 2
done
[[ "$ready" == true ]] || exit 1
test_db_port=$(docker port "$test_db_id" 5432/tcp | head -1 | cut -d: -f2)
export TEST_DATABASE_URL="postgres://orders:orders@127.0.0.1:$test_db_port/orders_test"
mkdir -p reports
node --test --test-concurrency=1 --test-reporter=spec --test-reporter-destination=stdout --test-reporter=junit --test-reporter-destination=reports/tests.xml test/*.test.js
