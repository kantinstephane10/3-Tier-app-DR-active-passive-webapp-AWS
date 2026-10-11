output "deployment_prefix" { value = var.prefix }
output "networks" {
  value = merge(
    { primary = { region = var.primary_region, vpc_id = module.network_primary.vpc_id, subnet_ids = module.network_primary.subnet_ids } },
    local.dr ? { secondary = { region = var.secondary_region, vpc_id = module.network_secondary[0].vpc_id, subnet_ids = module.network_secondary[0].subnet_ids } } : {}
  )
}
output "bastions" {
  value = merge(
    length(module.bastion_primary) > 0 ? { primary = { region = var.primary_region, instance_id = module.bastion_primary[0].instance_id } } : {},
    length(module.bastion_secondary) > 0 ? { secondary = { region = var.secondary_region, instance_id = module.bastion_secondary[0].instance_id } } : {}
  )
}
# Read by scripts/smoke-test.py.
output "regional" {
  value = merge(
    local.primary ? { primary = { region = var.primary_region, origin = module.regional_primary[0].origin_hostname, autoscaling_groups = module.regional_primary[0].autoscaling_groups } } : {},
    local.dr ? { secondary = { region = var.secondary_region, origin = module.regional_secondary[0].origin_hostname, autoscaling_groups = module.regional_secondary[0].autoscaling_groups } } : {}
  )
}
output "database" {
  value = local.primary ? {
    primary_endpoint       = module.database[0].primary_endpoint
    replica_endpoint       = module.database[0].replica_endpoint
    master_user_secret_arn = module.database[0].master_user_secret_arn
  } : null
}
output "backup_vaults" {
  value = merge(
    local.primary ? { primary = module.backup_primary[0].vault_name } : {},
    local.dr ? { secondary = module.backup_secondary[0].vault_name } : {}
  )
}
output "cloudfront_url" { value = local.edge ? module.edge[0].url : null }
output "cloudfront_distribution_id" { value = local.edge ? module.edge[0].distribution_id : null }
output "dns_name_servers" { value = local.dns ? module.dns[0].name_servers : [] }
output "custom_url" { value = local.dns ? "https://${module.dns[0].fqdn}" : null }
