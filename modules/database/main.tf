terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.secondary]
    }
  }
}
resource "aws_db_subnet_group" "primary" {
  name       = "${var.name}-primary"
  subnet_ids = var.primary_subnet_ids
}
# Multi-AZ primary with a synchronous standby in the second zone.
resource "aws_db_instance" "primary" {
  identifier                          = "${var.name}-primary"
  engine                              = "postgres"
  engine_version                      = var.engine_version
  instance_class                      = var.instance_class
  allocated_storage                   = 50
  max_allocated_storage               = 200
  storage_type                        = "gp3"
  storage_encrypted                   = true
  db_name                             = "app"
  username                            = var.admin_username
  manage_master_user_password         = true
  multi_az                            = true
  db_subnet_group_name                = aws_db_subnet_group.primary.name
  vpc_security_group_ids              = [var.primary_security_group_id]
  publicly_accessible                 = false
  iam_database_authentication_enabled = true
  backup_retention_period             = 7
  copy_tags_to_snapshot               = true
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${var.name}-primary-final"
  auto_minor_version_upgrade          = true
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]
}
data "aws_kms_alias" "rds_secondary" {
  provider = aws.secondary
  count    = var.enable_replica ? 1 : 0
  name     = "alias/aws/rds"
}
resource "aws_db_subnet_group" "secondary" {
  provider   = aws.secondary
  count      = var.enable_replica ? 1 : 0
  name       = "${var.name}-secondary"
  subnet_ids = var.secondary_subnet_ids
}
# Cross-region read replica; promote it during a regional failover.
resource "aws_db_instance" "replica" {
  provider                            = aws.secondary
  count                               = var.enable_replica ? 1 : 0
  identifier                          = "${var.name}-replica"
  replicate_source_db                 = aws_db_instance.primary.arn
  instance_class                      = var.replica_instance_class
  storage_type                        = "gp3"
  storage_encrypted                   = true
  kms_key_id                          = data.aws_kms_alias.rds_secondary[0].target_key_arn
  multi_az                            = var.replica_multi_az
  db_subnet_group_name                = aws_db_subnet_group.secondary[0].name
  vpc_security_group_ids              = [var.secondary_security_group_id]
  publicly_accessible                 = false
  iam_database_authentication_enabled = true
  backup_retention_period             = 7
  copy_tags_to_snapshot               = true
  deletion_protection                 = true
  skip_final_snapshot                 = true
  auto_minor_version_upgrade          = true
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]
}
output "primary_endpoint" { value = aws_db_instance.primary.address }
output "replica_endpoint" { value = var.enable_replica ? aws_db_instance.replica[0].address : null }
output "master_user_secret_arn" { value = aws_db_instance.primary.master_user_secret[0].secret_arn }
