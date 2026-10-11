variable "name" { type = string }
variable "engine_version" { type = string }
variable "instance_class" { type = string }
variable "admin_username" { type = string }
variable "primary_subnet_ids" { type = list(string) }
variable "primary_security_group_id" { type = string }
variable "enable_replica" { type = bool }
variable "replica_instance_class" { type = string }
variable "replica_multi_az" { type = bool }
variable "secondary_subnet_ids" {
  type    = list(string)
  default = []
}
variable "secondary_security_group_id" {
  type    = string
  default = null
}
