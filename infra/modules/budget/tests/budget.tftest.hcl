mock_provider "azurerm" {}

variables {
  name            = "budget-orders"
  subscription_id = "00000000-0000-0000-0000-000000000000"
  amount          = 20
  start_date      = "2026-11-01T00:00:00Z"
  contact_emails  = ["owner@example.com"]
}

run "alerts_at_80_and_100_percent_of_actual_spend" {
  command = plan

  assert {
    condition     = toset([for notification in azurerm_consumption_budget_subscription.this.notification : notification.threshold]) == toset([80, 100])
    error_message = "the budget must alert at 80 and 100 percent"
  }
}

run "refuses_a_start_date_that_is_not_the_first_of_a_month" {
  command = plan

  variables {
    start_date = "2026-11-15T00:00:00Z"
  }

  expect_failures = [var.start_date]
}

run "refuses_a_budget_that_alerts_nobody" {
  command = plan

  variables {
    contact_emails = []
  }

  expect_failures = [var.contact_emails]
}
