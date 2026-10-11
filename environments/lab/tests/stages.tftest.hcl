# Builds every rollout stage against mocked AWS providers: no credentials, no cloud resources.
# Run: terraform -chdir=environments/lab test

mock_provider "aws" {
  source = "./tests/mocks"
}
mock_provider "aws" {
  alias  = "secondary"
  source = "./tests/mocks"
}
mock_provider "aws" {
  alias  = "global"
  source = "./tests/mocks"
}
mock_provider "random" {}

variables {
  account_id     = "123456789012"
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK0wmN/Cr3JXqmLW7u+g9pTh+wyqDHpSQEC2MJbcE6Gh test"
}

run "foundation" {
  variables { stage = "foundation" }
  assert {
    condition     = length(module.network_secondary) == 0 && length(module.regional_primary) == 0 && length(module.database) == 0
    error_message = "foundation must only create the primary network and bastion."
  }
  assert {
    condition     = length(module.bastion_primary) == 1 && length(module.bastion_secondary) == 0
    error_message = "foundation must create only the primary bastion."
  }
}

run "primary" {
  variables { stage = "primary" }
  assert {
    condition     = length(module.regional_primary) == 1 && length(module.regional_secondary) == 0
    error_message = "primary must create only the primary compute stack."
  }
  assert {
    condition     = module.database[0].replica_endpoint == null
    error_message = "primary must not create the cross-region replica."
  }
  assert {
    condition     = keys(output.regional) == ["primary"]
    error_message = "regional output must list only the primary region."
  }
}

run "dr" {
  variables { stage = "dr" }
  assert {
    condition     = length(module.network_secondary) == 1 && length(module.regional_secondary) == 1 && length(module.bastion_secondary) == 1
    error_message = "dr must create the secondary region stack."
  }
  assert {
    condition     = module.database[0].replica_endpoint != null
    error_message = "dr must create the cross-region read replica."
  }
  assert {
    condition     = length(module.backup_secondary) == 1 && output.cloudfront_url == null
    error_message = "dr must add the secondary backup vault and no edge."
  }
}

run "edge" {
  variables { stage = "edge" }
  assert {
    condition     = startswith(output.cloudfront_url, "https://")
    error_message = "edge must publish the CloudFront URL."
  }
  assert {
    condition     = length(module.dns) == 0 && output.custom_url == null
    error_message = "edge without a domain must not create DNS resources."
  }
}

run "edge_with_domain" {
  variables {
    stage         = "edge"
    dns_zone_name = "example.com"
  }
  assert {
    condition     = output.custom_url == "https://app.example.com" && length(aws_route53_record.app) == 2
    error_message = "a domain must create the zone, certificate and A/AAAA alias records."
  }
}

run "rejects_unknown_stage" {
  command = plan
  variables { stage = "production" }
  expect_failures = [var.stage]
}

run "rejects_bad_account_id" {
  command = plan
  variables { account_id = "12345" }
  expect_failures = [var.account_id]
}
