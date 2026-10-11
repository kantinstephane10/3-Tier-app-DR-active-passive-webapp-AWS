# Run once with an operator's administrator login, never with the Jenkins user's keys.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags { tags = { owner = "Kantin Tongue", project = "aws-three-tier", environment = "lab" } }
}
