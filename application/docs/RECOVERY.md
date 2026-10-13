# Coordinated regional recovery drill

The diagram uses RDS PostgreSQL Multi-AZ plus a cross-region read replica. A Multi-AZ DB-instance standby is managed by RDS and is not a readable API endpoint. Use the primary DB endpoint after an AZ failover. The cross-region replica is asynchronous: regional recovery can lose transactions not replicated before the outage. Measure actual RPO/RTO; do not claim zero data loss from the diagram alone.

CloudFront origin groups fail over GET/HEAD/OPTIONS only, not POST checkout. This application intentionally does not automatically promote databases or switch CloudFront/Route 53. Perform this controlled drill with one authorized operator/runbook and record timestamps.

1. Confirm a known order is FULFILLED in primary. Record its ID, creation time and region. Record replica lag and confirm the same order exists in the replica using an authorized DB session.
2. In a planned drill, fence primary first: set WRITE_ENABLED=false across the primary app launch-template/runtime configuration, restart API/worker services, and verify checkout returns 503. Prevent old instances being relaunched with true. In an outage, establish infrastructure/network fencing sufficient to prevent the old writer/worker accepting orders if it recovers. A per-process flag alone is not a distributed fencing mechanism.
3. Promote the cross-region RDS PostgreSQL replica to a standalone writable database. Wait for availability and verify transaction_read_only is off. Do not run the Aurora promotion command for this RDS architecture.
4. Confirm the DR application secret points to the promoted database, with correct credentials and the same session key. Restart services if the secret changed. Only after primary fencing and database promotion, set WRITE_ENABLED=true for DR instances and their launch-template/runtime configuration. Verify `/health/ready` returns 200 through the regional HTTPS test hostname.
5. Update regions.json deliberately: DR mode=active with a prepared DR migration runner; original primary mode=standby. Do not run a primary DEPLOY with active mode against the fenced/old database. If no schema change is needed, activation does not require a new application release.
6. Switch the active CloudFront origin (or the established Route 53 origin-routing design) to DR for every request method, including POST. Wait for distribution/DNS changes and verify the global URL reports the expected region and accepts a new demo order. Do not rely solely on CloudFront GET failover. Browser sessions can continue because the regional secret shares the signing key, provided the relevant orders were replicated.
7. The new region's worker drains replicated unfinished jobs from PostgreSQL. Check known orders, retries and pending work; missing unreplicated orders cannot be reconstructed by this application. Record the last replicated order timestamp and observed availability recovery to calculate RPO/RTO.
8. Keep the previous region fenced. Replica promotion breaks its former replication relationship. Design/rebuild the reverse replication topology, reconcile divergence deliberately and verify it before planned failback. Do not simply turn both WRITE_ENABLED flags on or redirect traffic back to the old database.

For backup restoration, restore into a separate private DB, validate schema/data/permissions with an isolated app deployment, then plan cutover. A successful restore test does not prove the current replica is synchronized.

Operational inspection as an authorized DB user:

```sql
SHOW transaction_read_only;
SELECT version FROM schema_versions;
SELECT status, count(*) FROM orders GROUP BY status;
SELECT count(*) AS pending_jobs FROM jobs WHERE completed_at IS NULL;
```

Future real external fulfillment needs an idempotent downstream API and reconciliation design. The present worker performs database-only simulated fulfillment, so it can complete its status/job updates in one transaction.
