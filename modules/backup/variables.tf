variable "name" { type = string }
variable "backup_tag" { type = string }
variable "enable_copy" { type = bool }
variable "copy_vault_arn" {
  type    = string
  default = null
}
variable "retention_days" {
  type    = number
  default = 30
}
