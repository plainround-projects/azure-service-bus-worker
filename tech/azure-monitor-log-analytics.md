# Log Analytics, diagnostic settings and the dead-letter alert

*Where the namespace's logs go and what mails you when a dead letter appears. Pinned here: Log Analytics PerGB2018, Azure Monitor metric alert.*

## What it is

A **Log Analytics workspace** is a store for logs that you can query. **Diagnostic settings** tell an Azure resource to send its logs and metrics to a workspace. **Kusto Query Language (KQL)** is the language you use to ask the workspace questions. **Azure Monitor** also has **alert rules** that send a message when a condition holds.

## Why this repository uses it

The runbook's third signal is a dead-letter count above zero. An alert rule turns that signal into an email.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/log_analytics/` | The workspace. |
| `infra/modules/servicebus/main.tf` | Diagnostic setting, action group and metric alert. |

## How it works underneath

Each service has named **log categories**. Key Vault's `AuditEvent` records every data-plane call. Storage has `StorageRead`, `StorageWrite` and `StorageDelete`. Service Bus has `OperationalLogs`. A diagnostic setting picks categories and a destination. Logs land in the workspace a few minutes after they happen, in tables such as `AzureDiagnostics` or `StorageBlobLogs`.

A KQL query is a pipeline: `Table | where Status == 403 | project TimeGenerated, Caller | order by TimeGenerated desc`. The `|` passes the rows to the next step. A **metric alert** watches a number (for example the dead-letter message count) and fires when it passes a threshold, notifying an **action group** (an email list).

The workspace's first 5 GB of ingestion each month are free on the pay-as-you-go tier; retention beyond 30 days costs extra.

## Walkthrough of this repository's use

```hcl
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
```

Sends the namespace's `OperationalLogs` (entity management operations) and all metrics to the workspace.

```hcl
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
```

An **action group** is the list of people to notify. `count = length(var.alert_email_addresses) > 0 ? 1 : 0` creates it only when there are recipients. `dynamic "email_receiver"` repeats the block for each address.

```hcl
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
```

A **metric alert** watches one number every minute (`frequency = "PT1M"`) over a five-minute window: `DeadletteredMessages`, with aggregation `Maximum`. When it is greater than 0 the alert fires and notifies the action group.

## Try it yourself

Run the namespace module's tests, including no alert without recipients.

```bash
cd infra/modules/servicebus && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -4
```

You should see something like this:

```text
tests/servicebus.tftest.hcl... tearing down
tests/servicebus.tftest.hcl... pass

Success! 9 passed, 0 failed.
```

Run the workspace tests.

```bash
cd infra/modules/log_analytics && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -3
```

You should see something like this:

```text
tests/log_analytics.tftest.hcl... pass

Success! 2 passed, 0 failed.
```

## Mistakes people make

- Querying right after an event and finding nothing: ingestion has a delay.
- Forgetting to enable the category you need; no category, no log.
- Assuming column names. Check the table's schema in the portal; the queries in the runbook were not run against a live workspace.
- Sending logs nowhere. A denial that is not logged cannot be investigated.
- Alerts with no recipients: nobody is told.

## Check yourself

1. **What is a diagnostic setting?**
   Answer: A configuration that sends a resource's logs and metrics to a destination such as a workspace.

2. **What does `AuditEvent` record?**
   Answer: Each data-plane request to a vault, including denials.

3. **What does `|` do in KQL?**
   Answer: Passes the rows of one step to the next.

4. **Why can a fresh query be empty?**
   Answer: Logs arrive in the workspace some minutes after the event.

5. **What is an action group?**
   Answer: The list of recipients and actions that an alert notifies.

## Further reading

- Log Analytics: https://learn.microsoft.com/en-us/azure/azure-monitor/logs/log-analytics-overview
- KQL: https://learn.microsoft.com/en-us/kusto/query/
- Diagnostic settings: https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/diagnostic-settings
- Metric alerts: https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-metric-overview
