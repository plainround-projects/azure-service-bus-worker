mock_provider "azurerm" {}

variables {
  name                = "acrorders12345"
  resource_group_name = "rg-test"
  location            = "westeurope"
}

run "has_no_admin_user_and_no_anonymous_pull" {
  command = plan

  assert {
    condition     = azurerm_container_registry.this.admin_enabled == false && azurerm_container_registry.this.anonymous_pull_enabled == false
    error_message = "the registry must not offer a shared password or anonymous pulls"
  }
}

run "refuses_a_name_with_a_hyphen" {
  command = plan

  variables {
    name = "acr-orders"
  }

  expect_failures = [var.name]
}
