# Controlled failover exercise

Run after the `edge` deployment succeeds. This is a manual drill, not automatic remediation.

1. Confirm both regions are healthy: target groups of both ALBs show healthy targets, and the RDS replica's `ReplicaLag` metric is low. Check that each tier has instances in both Availability Zones.
2. Before moving real traffic, make sure the application can switch its database endpoint. The demo app never queries the database, so its HTTP response only proves the routing path.
3. If the secondary needs more capacity, set `standby_instance_type` to the primary type, keep `ROLLOUT=edge`, run PLAN, review, then APPLY. The launch template gets a new version; the Auto Scaling group's instance refresh (or replacing instances one at a time) rolls it out. Keep at least one healthy instance per tier.
4. **Simulate a primary outage at the edge.** Set the primary web Auto Scaling group's desired and minimum capacity to 0 (console or `aws autoscaling update-auto-scaling-group`). The primary ALB returns 503, and CloudFront retries the same request on the secondary origin.
5. Request the CloudFront URL repeatedly. The JSON `region` changes from the primary to the secondary region. Record the time to stable service.
6. **Promote the database** only if the drill includes a data-layer failover: RDS → `kt-lab-replica` → Actions → Promote. Promotion is one-way. The promoted instance becomes standalone and writable, and the original primary no longer receives its changes. Record the replica lag at promotion time as your measured RPO.
7. Point the application at the promoted endpoint, then test reads and writes.
8. Restore: return the primary Auto Scaling group to its original capacity. Once the primary origin answers without 5xx, CloudFront sends traffic to it again.
9. After a promotion, rebuild replication deliberately: decide which database is authoritative, then recreate a replica from it. Terraform still describes the old topology, so plan carefully. The deletion guard will stop a plan that tries to replace the promoted instance, and that is intended.
10. Run Jenkins PLAN with `ROLLOUT=edge` to see and reconcile any console drift.

Limitations to keep in mind:

- CloudFront origin failover works per request. It applies to GET, HEAD and OPTIONS and is triggered by 500/502/503/504 responses or connection timeouts. There are no background health probes. For write traffic or health-based switching, use Route 53 failover records in front of the ALBs.
- Replication from the primary to the cross-region replica is asynchronous. A promotion after a sudden primary loss can lose the most recent writes.

# Backup restore exercise

In AWS Backup, open `kt-lab-primary-vault` and check that recent recovery points exist for the web and app instances (tag `backup = kt-lab`). Then open `kt-lab-secondary-vault` and check that the cross-region copies have arrived. Restore one copy in the secondary region into an isolated subnet and confirm the instance boots and serves `/health`. A restored instance is not part of an Auto Scaling group or target group; production recovery relies on the Auto Scaling groups and launch templates, and backups cover instance-level data.

RDS has its own automated backups (7 days) in both regions, plus point-in-time restore. Test a point-in-time restore of the primary into a new instance identifier and compare the data.
