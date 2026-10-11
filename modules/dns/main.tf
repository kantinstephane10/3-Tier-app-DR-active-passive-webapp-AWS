terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
locals {
  fqdn = "${var.host_label}.${var.zone_name}"
}
resource "aws_route53_zone" "this" {
  name = var.zone_name
}
# CloudFront certificates must live in us-east-1.
resource "aws_acm_certificate" "this" {
  domain_name       = local.fqdn
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "validation" {
  for_each        = toset([local.fqdn])
  zone_id         = aws_route53_zone.this.zone_id
  name            = one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_name if o.domain_name == each.key])
  type            = one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_type if o.domain_name == each.key])
  records         = [one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_value if o.domain_name == each.key])]
  ttl             = 60
  allow_overwrite = true
}
resource "aws_acm_certificate_validation" "this" {
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}
output "zone_id" { value = aws_route53_zone.this.zone_id }
output "name_servers" { value = aws_route53_zone.this.name_servers }
output "fqdn" { value = local.fqdn }
output "certificate_arn" { value = aws_acm_certificate_validation.this.certificate_arn }
