resource "azurerm_servicebus_namespace" "this" {
  #checkov:skip=CKV_AZURE_201:customer-managed keys need the Premium tier; Standard is the cheapest tier that has sessions
  #checkov:skip=CKV_AZURE_199:double encryption needs the Premium tier
  #checkov:skip=CKV_AZURE_202:the namespace makes no outbound calls, so it needs no identity of its own
  #checkov:skip=CKV_AZURE_204:private endpoints and network rules need the Premium tier; access is Entra ID only (local_auth_enabled = false)
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard" # sessions need Standard or Premium; Standard is the cheaper of the two
  tags                = var.tags

  # Entra ID only: shared access signatures and the connection strings that carry them stop working, so the producer
  # and the worker can authenticate with nothing but their identities.
  local_auth_enabled  = false
  minimum_tls_version = "1.2"
}

resource "azurerm_servicebus_queue" "this" {
  for_each = var.queues

  name         = each.key
  namespace_id = azurerm_servicebus_namespace.this.id

  lock_duration      = each.value.lock_duration
  max_delivery_count = each.value.max_delivery_count
  requires_session   = each.value.requires_session

  # A message that expires unprocessed goes to the dead-letter queue instead of vanishing.
  dead_lettering_on_message_expiration = true
  default_message_ttl                  = each.value.default_message_ttl
  max_size_in_megabytes                = 1024
}

resource "azurerm_monitor_diagnostic_setting" "namespace" {
  name                       = "to-log-analytics"
  target_resource_id         = azurerm_servicebus_namespace.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "OperationalLogs"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}

resource "azurerm_monitor_action_group" "dead_letters" {
  count = length(var.alert_email_addresses) > 0 ? 1 : 0

  name                = "ag-${var.name}-dead-letters"
  resource_group_name = var.resource_group_name
  short_name          = "deadltr"
  tags                = var.tags

  dynamic "email_receiver" {
    for_each = toset(var.alert_email_addresses)
    content {
      name                    = "mail-${index(var.alert_email_addresses, email_receiver.value)}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

# The runbook's third signal: a dead-letter count above zero means a command that could never succeed is waiting.
resource "azurerm_monitor_metric_alert" "dead_letters" {
  count = length(var.alert_email_addresses) > 0 ? 1 : 0

  name                = "alert-${var.name}-dead-letters"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_servicebus_namespace.this.id]
  description         = "At least one message is in a dead-letter queue. Read it with order-dlq (docs/RUNBOOK.md)."
  severity            = 2
  frequency           = "PT1M"
  window_size         = "PT5M"
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.ServiceBus/namespaces"
    metric_name      = "DeadletteredMessages"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 0
  }

  action {
    action_group_id = azurerm_monitor_action_group.dead_letters[0].id
  }
}
