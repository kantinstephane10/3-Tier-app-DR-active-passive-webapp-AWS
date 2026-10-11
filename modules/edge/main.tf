terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
# CloudFront-scoped WAF resources must be created in us-east-1.
resource "aws_wafv2_web_acl" "this" {
  name  = "waf-${var.name}"
  scope = "CLOUDFRONT"
  default_action {
    allow {}
  }
  dynamic "rule" {
    for_each = { 1 = "AWSManagedRulesCommonRuleSet", 2 = "AWSManagedRulesKnownBadInputsRuleSet", 3 = "AWSManagedRulesAmazonIpReputationList" }
    content {
      name     = rule.value
      priority = rule.key
      override_action {
        none {}
      }
      statement {
        managed_rule_group_statement {
          name        = rule.value
          vendor_name = "AWS"
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.value
        sampled_requests_enabled   = true
      }
    }
  }
  rule {
    name     = "rate-limit"
    priority = 10
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "waf-${var.name}"
    sampled_requests_enabled   = true
  }
}
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}
locals {
  failover = length(var.origins) > 1
}
resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = "Kantin Tongue ${var.name}"
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_100"
  web_acl_id      = aws_wafv2_web_acl.this.arn
  aliases         = var.aliases
  dynamic "origin" {
    for_each = var.origins
    content {
      origin_id   = origin.key
      domain_name = origin.value
      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "http-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
      custom_header {
        name  = "X-Origin-Verify"
        value = var.origin_secret
      }
    }
  }
  # Active/passive: requests go to the primary and fail over to the secondary on 5xx or timeouts.
  dynamic "origin_group" {
    for_each = local.failover ? [1] : []
    content {
      origin_id = "regional"
      failover_criteria { status_codes = [500, 502, 503, 504] }
      member { origin_id = "primary" }
      member { origin_id = "secondary" }
    }
  }
  default_cache_behavior {
    target_origin_id         = local.failover ? "regional" : "primary"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    cloudfront_default_certificate = var.certificate_arn == null
    acm_certificate_arn            = var.certificate_arn
    ssl_support_method             = var.certificate_arn == null ? null : "sni-only"
    minimum_protocol_version       = var.certificate_arn == null ? "TLSv1" : "TLSv1.2_2021"
  }
}
output "url" { value = "https://${aws_cloudfront_distribution.this.domain_name}" }
output "domain_name" { value = aws_cloudfront_distribution.this.domain_name }
output "hosted_zone_id" { value = aws_cloudfront_distribution.this.hosted_zone_id }
output "distribution_id" { value = aws_cloudfront_distribution.this.id }
output "web_acl_arn" { value = aws_wafv2_web_acl.this.arn }
