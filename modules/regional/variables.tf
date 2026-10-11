variable "name" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = map(list(string)) }
variable "security_group_ids" { type = map(string) }
variable "instance_type" { type = string }
variable "instances" { type = number }
variable "max_instances" { type = number }
variable "key_name" { type = string }
variable "database_endpoint" { type = string }
variable "backup_tag" { type = string }
variable "tags" { type = map(string) }
variable "origin_secret" {
  type      = string
  sensitive = true
}
