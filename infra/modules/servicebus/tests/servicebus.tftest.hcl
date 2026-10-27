mock_provider "azurerm" {}

variables {
  name                       = "sb-orders-abcde"
  resource_group_name        = "rg-test"
  location                   = "westeurope"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.OperationalInsights/workspaces/law-test"
  queues = {
    orders          = {}
    orders-sessions = { requires_session = true }
  }
}

run "is_standard_tier_and_accepts_only_entra_authentication" {
  command = plan

  assert {
    condition     = azurerm_servicebus_namespace.this.sku == "Standard"
    error_message = "sessions need the Standard tier"
  }

  assert {
    condition     = azurerm_servicebus_namespace.this.local_auth_enabled == false && azurerm_servicebus_namespace.this.minimum_tls_version == "1.2"
    error_message = "shared access keys must be off and TLS 1.2 required"
  }
}

run "queues_follow_the_lesson_a_30_second_lock_and_ten_deliveries" {
  command = plan

  assert {
    condition     = alltrue([for queue in azurerm_servicebus_queue.this : queue.lock_duration == "PT30S" && queue.max_delivery_count == 10])
    error_message = "every queue needs a 30 s lock and a maximum delivery count of 10"
  }

  assert {
    condition     = alltrue([for queue in azurerm_servicebus_queue.this : queue.dead_lettering_on_message_expiration])
    error_message = "expired messages must be dead-lettered, not dropped"
  }
}

run "only_the_session_queue_requires_sessions" {
  command = plan

  assert {
    condition     = azurerm_servicebus_queue.this["orders-sessions"].requires_session && !azurerm_servicebus_queue.this["orders"].requires_session
    error_message = "orders-sessions requires sessions, orders does not"
  }
}

run "logs_and_metrics_go_to_the_workspace" {
  command = plan

  assert {
    condition     = one(azurerm_monitor_diagnostic_setting.namespace.enabled_log).category == "OperationalLogs"
    error_message = "operational logs must be enabled"
  }
}

run "no_alert_without_recipients" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_metric_alert.dead_letters) == 0 && length(azurerm_monitor_action_group.dead_letters) == 0
    error_message = "an alert that mails nobody must not be created"
  }
}

run "alerts_on_any_dead_letter_when_recipients_are_given" {
  command = plan

  variables {
    alert_email_addresses = ["owner@example.com"]
  }

  assert {
    condition     = one(azurerm_monitor_metric_alert.dead_letters[0].criteria).metric_name == "DeadletteredMessages" && one(azurerm_monitor_metric_alert.dead_letters[0].criteria).threshold == 0
    error_message = "the alert must fire when the dead-letter count is above zero"
  }
}

run "refuses_a_delivery_count_of_zero" {
  command = plan

  variables {
    queues = { orders = { max_delivery_count = 0 } }
  }

  expect_failures = [var.queues]
}

run "refuses_a_lock_duration_that_is_not_an_iso_duration" {
  command = plan

  variables {
    queues = { orders = { lock_duration = "30 seconds" } }
  }

  expect_failures = [var.queues]
}

run "refuses_a_short_name" {
  command = plan

  variables {
    name = "sb"
  }

  expect_failures = [var.name]
}
