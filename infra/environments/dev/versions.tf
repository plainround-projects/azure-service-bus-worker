terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Local state keeps the practice run self-contained. For a shared environment copy backend.hcl.example to
  # backend.hcl, uncomment the block below and run `terraform init -backend-config=backend.hcl`.
  # backend "azurerm" {}
}
