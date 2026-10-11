terraform {
  required_version = ">= 1.12.2, < 2.0.0"
  backend "local" {
    path          = "/var/lib/jenkins/terraform-state/kt-aws-lab/infrastructure.tfstate"
    workspace_dir = "/var/lib/jenkins/terraform-state/kt-aws-lab/workspaces"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.68.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
  }
}
