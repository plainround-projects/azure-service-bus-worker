mock_provider "azurerm" {}

variables {
  name                = "law-test"
  resource_group_name = "rg-test"
  location            = "westeurope"
}

run "keeps_logs_for_the_free_retention_by_default" {
  command = plan

  assert {
    condition     = azurerm_log_analytics_workspace.this.retention_in_days == 30
    error_message = "the default retention must be the free 30 days"
  }
}

run "refuses_retention_below_the_tier_minimum" {
  command = plan

  variables {
    retention_in_days = 7
  }

  expect_failures = [var.retention_in_days]
}
