# Credentials come from the AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables Jenkins binds.
provider "aws" {
  region              = var.primary_region
  allowed_account_ids = [var.account_id]
  default_tags { tags = var.tags }
}
provider "aws" {
  alias               = "secondary"
  region              = var.secondary_region
  allowed_account_ids = [var.account_id]
  default_tags { tags = var.tags }
}
# CloudFront WAF, ACM certificates and Route 53 are managed from us-east-1.
provider "aws" {
  alias               = "global"
  region              = "us-east-1"
  allowed_account_ids = [var.account_id]
  default_tags { tags = var.tags }
}
