provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id

  # scripts/provision.sh registers the resource providers this slice needs, so the plan never changes
  # subscription-wide settings on its own.
  resource_provider_registrations = "none"

  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
