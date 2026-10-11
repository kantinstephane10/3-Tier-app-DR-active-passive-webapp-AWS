locals {
  ranks   = { foundation = 0, primary = 1, dr = 2, edge = 3 }
  rank    = lookup(local.ranks, var.stage, -1)
  primary = local.rank >= 1
  dr      = local.rank >= 2
  edge    = local.rank >= 3
  dns     = local.edge && var.dns_zone_name != ""
}
check "stage" {
  assert {
    condition     = contains(keys(local.ranks), var.stage)
    error_message = "stage must be foundation, primary, dr, or edge."
  }
}
# Shared secret CloudFront sends to the ALBs; requests without it get 403.
resource "random_password" "origin_secret" {
  length  = 48
  special = false
}
resource "aws_key_pair" "primary" {
  key_name   = "${var.prefix}-primary"
  public_key = var.ssh_public_key
}
resource "aws_key_pair" "secondary" {
  provider   = aws.secondary
  count      = local.dr ? 1 : 0
  key_name   = "${var.prefix}-secondary"
  public_key = var.ssh_public_key
}

# Foundation: networks and bastions.
module "network_primary" {
  source     = "../../modules/network"
  name       = "${var.prefix}-primary"
  cidr       = "10.10.0.0/16"
  enable_nat = var.enable_nat
}
module "network_secondary" {
  source     = "../../modules/network"
  count      = local.dr ? 1 : 0
  providers  = { aws = aws.secondary }
  name       = "${var.prefix}-secondary"
  cidr       = "10.20.0.0/16"
  enable_nat = var.enable_nat
}
module "bastion_primary" {
  source            = "../../modules/bastion"
  count             = var.enable_bastion ? 1 : 0
  name              = "${var.prefix}-primary"
  subnet_id         = module.network_primary.subnet_ids["public"][0]
  security_group_id = module.network_primary.security_group_ids["bastion"]
  key_name          = aws_key_pair.primary.key_name
}
module "bastion_secondary" {
  source            = "../../modules/bastion"
  count             = var.enable_bastion && local.dr ? 1 : 0
  providers         = { aws = aws.secondary }
  name              = "${var.prefix}-secondary"
  subnet_id         = module.network_secondary[0].subnet_ids["public"][0]
  security_group_id = module.network_secondary[0].security_group_ids["bastion"]
  key_name          = aws_key_pair.secondary[0].key_name
}

# Primary and DR: database, compute and backup.
module "database" {
  source                      = "../../modules/database"
  count                       = local.primary ? 1 : 0
  providers                   = { aws = aws, aws.secondary = aws.secondary }
  name                        = var.prefix
  engine_version              = var.db_engine_version
  instance_class              = var.db_instance_class
  admin_username              = var.db_admin_username
  primary_subnet_ids          = module.network_primary.subnet_ids["db"]
  primary_security_group_id   = module.network_primary.security_group_ids["db"]
  enable_replica              = local.dr
  replica_instance_class      = var.db_replica_instance_class
  replica_multi_az            = var.db_replica_multi_az
  secondary_subnet_ids        = local.dr ? module.network_secondary[0].subnet_ids["db"] : []
  secondary_security_group_id = local.dr ? module.network_secondary[0].security_group_ids["db"] : null
}
module "regional_primary" {
  source             = "../../modules/regional"
  count              = local.primary ? 1 : 0
  name               = "${var.prefix}-primary"
  region             = var.primary_region
  vpc_id             = module.network_primary.vpc_id
  subnet_ids         = module.network_primary.subnet_ids
  security_group_ids = module.network_primary.security_group_ids
  instance_type      = var.instance_type
  instances          = var.instances
  max_instances      = var.max_instances
  key_name           = aws_key_pair.primary.key_name
  database_endpoint  = module.database[0].primary_endpoint
  backup_tag         = var.prefix
  tags               = var.tags
  origin_secret      = random_password.origin_secret.result
  depends_on         = [module.network_primary]
}
module "regional_secondary" {
  source             = "../../modules/regional"
  count              = local.dr ? 1 : 0
  providers          = { aws = aws.secondary }
  name               = "${var.prefix}-secondary"
  region             = var.secondary_region
  vpc_id             = module.network_secondary[0].vpc_id
  subnet_ids         = module.network_secondary[0].subnet_ids
  security_group_ids = module.network_secondary[0].security_group_ids
  instance_type      = var.standby_instance_type
  instances          = var.instances
  max_instances      = var.max_instances
  key_name           = aws_key_pair.secondary[0].key_name
  database_endpoint  = module.database[0].replica_endpoint
  backup_tag         = var.prefix
  tags               = var.tags
  origin_secret      = random_password.origin_secret.result
  depends_on         = [module.network_secondary]
}
module "backup_primary" {
  source         = "../../modules/backup"
  count          = local.primary ? 1 : 0
  name           = "${var.prefix}-primary"
  backup_tag     = var.prefix
  enable_copy    = local.dr
  copy_vault_arn = local.dr ? module.backup_secondary[0].vault_arn : null
}
module "backup_secondary" {
  source      = "../../modules/backup"
  count       = local.dr ? 1 : 0
  providers   = { aws = aws.secondary }
  name        = "${var.prefix}-secondary"
  backup_tag  = var.prefix
  enable_copy = false
}

# Edge: CloudFront, WAF and optional Route 53 domain.
module "dns" {
  source     = "../../modules/dns"
  count      = local.dns ? 1 : 0
  providers  = { aws = aws.global }
  zone_name  = var.dns_zone_name
  host_label = var.dns_host_label
}
module "edge" {
  source    = "../../modules/edge"
  count     = local.edge ? 1 : 0
  providers = { aws = aws.global }
  name      = var.prefix
  origins = merge(
    { primary = module.regional_primary[0].origin_hostname },
    local.dr ? { secondary = module.regional_secondary[0].origin_hostname } : {}
  )
  origin_secret   = random_password.origin_secret.result
  aliases         = local.dns ? [module.dns[0].fqdn] : []
  certificate_arn = local.dns ? module.dns[0].certificate_arn : null
}
resource "aws_route53_record" "app" {
  provider = aws.global
  for_each = local.dns ? toset(["A", "AAAA"]) : toset([])
  zone_id  = module.dns[0].zone_id
  name     = module.dns[0].fqdn
  type     = each.key
  alias {
    name                   = module.edge[0].domain_name
    zone_id                = module.edge[0].hosted_zone_id
    evaluate_target_health = false
  }
}
