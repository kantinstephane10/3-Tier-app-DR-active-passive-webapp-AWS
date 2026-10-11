variable "name" { type = string }
variable "origins" {
  type        = map(string)
  description = "Origin ID (primary, secondary) to ALB hostname."
}
variable "origin_secret" {
  type      = string
  sensitive = true
}
variable "aliases" {
  type    = list(string)
  default = []
}
variable "certificate_arn" {
  type    = string
  default = null
}
