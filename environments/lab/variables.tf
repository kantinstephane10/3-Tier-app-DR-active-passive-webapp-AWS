variable "account_id" {
  type        = string
  description = "AWS account ID. Terraform refuses to run against any other account."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}
variable "prefix" {
  type    = string
  default = "kt-lab"
}
variable "stage" {
  type    = string
  default = "foundation"
  validation {
    condition     = contains(["foundation", "primary", "dr", "edge"], var.stage)
    error_message = "Select foundation, primary, dr, or edge."
  }
}
variable "primary_region" {
  type    = string
  default = "us-east-1"
}
variable "secondary_region" {
  type    = string
  default = "us-west-2"
}
variable "ssh_public_key" {
  type = string
}
variable "instance_type" {
  type    = string
  default = "m6i.large"
}
variable "standby_instance_type" {
  type    = string
  default = "t3.medium"
}
variable "instances" {
  type    = number
  default = 2
}
variable "max_instances" {
  type    = number
  default = 4
}
variable "db_engine_version" {
  type    = string
  default = "16"
}
variable "db_instance_class" {
  type    = string
  default = "db.m6g.large"
}
variable "db_replica_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "db_replica_multi_az" {
  type    = bool
  default = true
}
variable "db_admin_username" {
  type    = string
  default = "ktadmin"
}
variable "enable_bastion" {
  type    = bool
  default = true
}
variable "enable_nat" {
  type    = bool
  default = true
}
variable "tags" {
  type    = map(string)
  default = { owner = "Kantin Tongue", project = "aws-three-tier", environment = "lab" }
}
variable "dns_zone_name" {
  type        = string
  default     = ""
  description = "Optional domain you own. Empty uses the CloudFront default hostname."
}
variable "dns_host_label" {
  type    = string
  default = "app"
}
