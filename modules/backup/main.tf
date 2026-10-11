terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
resource "aws_backup_vault" "this" {
  name = "${var.name}-vault"
}
resource "aws_iam_role" "backup" {
  name = "${var.name}-backup"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "backup.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy_attachment" "backup" {
  for_each   = toset(["AWSBackupServiceRolePolicyForBackup", "AWSBackupServiceRolePolicyForRestores"])
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/${each.key}"
}
resource "aws_backup_plan" "this" {
  name = "${var.name}-daily"
  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.this.name
    schedule          = "cron(0 3 * * ? *)"
    lifecycle { delete_after = var.retention_days }
    dynamic "copy_action" {
      for_each = var.enable_copy ? [1] : []
      content {
        destination_vault_arn = var.copy_vault_arn
        lifecycle { delete_after = var.retention_days }
      }
    }
  }
}
# Tag-based selection also protects instances that Auto Scaling launches later.
resource "aws_backup_selection" "this" {
  name         = "${var.name}-tagged"
  plan_id      = aws_backup_plan.this.id
  iam_role_arn = aws_iam_role.backup.arn
  selection_tag {
    type  = "STRINGEQUALS"
    key   = "backup"
    value = var.backup_tag
  }
}
output "vault_name" { value = aws_backup_vault.this.name }
output "vault_arn" { value = aws_backup_vault.this.arn }
output "plan_id" { value = aws_backup_plan.this.id }
