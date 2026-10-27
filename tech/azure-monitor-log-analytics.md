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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/log_analytics/main.tf`

8 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 8**

```hcl
resource "azurerm_log_analytics_workspace" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  tags                = var.tags
}
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** **Log Analytics** is Azure's store for logs and metrics, queried with the Kusto Query Language (KQL). A *diagnostic setting* tells a resource to send its logs there, so that, for example, every refused request to a vault can be found afterwards.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_log_analytics_workspace" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_log_analytics_workspace.this`. A **Log Analytics workspace** is Azure's store for logs and metrics. Other resources send their diagnostics here, and you query it with the Kusto query language (KQL).
- `name                = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Workspace name, for example law-orders).
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the workspace).
- `location            = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `sku                 = "PerGB2018"`: `sku`: The pricing tier / capability level (the SKU) of the service. Here: the text `"PerGB2018"`.
- `retention_in_days   = var.retention_in_days`: `retention_in_days`: How many days the workspace keeps data before deleting it. Here: the input variable `retention_in_days` (How long logs stay queryable. 30 days is the free retention of the PerGB2018 tier).
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the workspace).
- Closing line: `}` ends the block opened above.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/environments/dev/main.tf` | 76 to 77, 109, 142 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/outputs.tf` | 3, 8, 12 to 13 | [terraform.md](terraform.md) |
| `infra/environments/dev/outputs.tf` | 46 to 48 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/main.tf` | 35 to 37 | [azure-service-bus.md](azure-service-bus.md) |
| `infra/environments/dev/tests/dev.tftest.hcl` | 21 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/tests/log_analytics.tftest.hcl` | 13 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/tests/servicebus.tftest.hcl` | 7 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/variables.tf` | 44 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/main.tf` | 5 | [azure-container-apps.md](azure-container-apps.md) |
| `infra/modules/worker_app/tests/worker_app.tftest.hcl` | 8 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/variables.tf` | 21 | [terraform.md](terraform.md) |
| `src/order_worker/infrastructure/logging.py` | 1 | [python.md](python.md) |

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
