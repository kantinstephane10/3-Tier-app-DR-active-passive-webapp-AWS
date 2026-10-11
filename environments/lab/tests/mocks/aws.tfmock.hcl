# Realistic values for data sources and computed attributes the configuration indexes into.
mock_data "aws_availability_zones" {
  defaults = { names = ["zone-a", "zone-b", "zone-c"] }
}
mock_data "aws_ssm_parameter" {
  defaults = { insecure_value = "ami-0123456789abcdef0" }
}
mock_data "aws_ec2_managed_prefix_list" {
  defaults = { id = "pl-3b927c52" }
}
mock_data "aws_kms_alias" {
  defaults = { target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/11111111-2222-3333-4444-555555555555" }
}
mock_data "aws_cloudfront_cache_policy" {
  defaults = { id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" }
}
mock_data "aws_cloudfront_origin_request_policy" {
  defaults = { id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" }
}
mock_resource "aws_db_instance" {
  defaults = {
    arn                = "arn:aws:rds:us-east-1:123456789012:db:kt-lab-primary"
    address            = "kt-lab.example.rds.amazonaws.com"
    master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds-test", kms_key_id = "", secret_status = "active" }]
  }
}
mock_resource "aws_acm_certificate" {
  defaults = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
    domain_validation_options = [{
      domain_name           = "app.example.com"
      resource_record_name  = "_test.app.example.com."
      resource_record_type  = "CNAME"
      resource_record_value = "_test.acm-validations.aws."
    }]
  }
}
mock_resource "aws_acm_certificate_validation" {
  defaults = { certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/test" }
}
mock_resource "aws_wafv2_web_acl" {
  defaults = { arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/waf-kt-lab/test" }
}
mock_resource "aws_cloudfront_distribution" {
  defaults = { domain_name = "d111111abcdef8.cloudfront.net", hosted_zone_id = "Z2FDTNDATAQYW2" }
}
mock_resource "aws_iam_role" {
  defaults = { arn = "arn:aws:iam::123456789012:role/kt-lab-test" }
}
mock_resource "aws_lb" {
  defaults = {
    arn      = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/kt-lab/50dc6c495c0c9188"
    dns_name = "kt-lab-123456789.us-east-1.elb.amazonaws.com"
  }
}
mock_resource "aws_lb_target_group" {
  defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/kt-lab/73e2d6bc24d8a067" }
}
mock_resource "aws_lb_listener" {
  defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/kt-lab/50dc6c495c0c9188/f2f7dc8efc522ab2" }
}
mock_resource "aws_launch_template" {
  defaults = { id = "lt-0123456789abcdef0" }
}
mock_resource "aws_backup_vault" {
  defaults = { arn = "arn:aws:backup:us-west-2:123456789012:backup-vault:kt-lab-secondary-vault" }
}
