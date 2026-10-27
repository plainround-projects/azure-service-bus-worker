# Azure Service Bus

*The broker whose three classic failures the lesson causes on purpose. Pinned here: Standard tier namespace, Entra ID only.*

## What it is

Azure Service Bus is a managed message broker. A **namespace** holds **queues**. A producer sends a message to a queue; a consumer receives it later. The queue stores messages until they are processed, so the two sides do not need to be running at the same time.

## Why this repository uses it

The lesson builds a consumer and breaks it in three ways: a lock that expires, commands for one customer handled out of order, and a message that can never succeed.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/servicebus/` | The namespace, the two queues, logs and the dead-letter alert. |
| `src/order_worker/infrastructure/servicebus.py` | The adapter. |
| `src/order_worker/infrastructure/simulation.py` | A simulated broker for offline runs. |
| `scripts/show-queues.sh` | Reads queue properties. |

## How it works underneath

Each queue has settings: the **lock duration** (how long a received message is hidden, here 30 seconds, at most 5 minutes), the **maximum delivery count** (10), whether it **requires sessions**, and a **time to live**. A message received in peek-lock mode must be completed before the lock expires or it comes back. Messages that fail too often, or are explicitly dead-lettered, go to the queue's **dead-letter queue**, a sub-queue read with its own receiver.

The **Standard** tier supports sessions and costs a monthly base charge; Premium adds private endpoints. This namespace sets `local_auth_enabled = false`, which turns off shared access keys, so only Entra ID tokens work. Roles: `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver`, and the broad `Data Owner`, which this repository refuses to assign.

## Walkthrough of this repository's use

```hcl
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
```

`sku = "Standard"` is the cheapest tier with sessions. `local_auth_enabled = false` turns off shared access keys, so only Entra ID tokens work: there is no connection string anywhere. `minimum_tls_version = "1.2"`.

```hcl
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
```

One queue per entry of the `queues` variable. `lock_duration` is the peek-lock time (`PT30S`: 30 seconds). `max_delivery_count` (10) is how many times the broker delivers a message before dead-lettering it. `requires_session` cannot be changed later, which is why the session queue is a second queue. `dead_lettering_on_message_expiration = true` sends expired messages to the dead-letter queue instead of dropping them.

```hcl
module "servicebus" {
  source = "../../modules/servicebus"

  name                       = local.names.namespace
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = module.log_analytics.id
  alert_email_addresses      = var.alert_email_addresses
  tags                       = local.tags

  queues = {
    orders          = {}
    orders-sessions = { requires_session = true }
  }
}
```

The two queues: `orders` and `orders-sessions`.

### The simulated broker

```python
    def _lock_is_valid(self, message: _Message, token: int) -> bool:
        if message.state is not _State.LOCKED or message.lock_token != token:
            return False
        if self.sessions:
            return True
        now = self.clock.now()
        return now < message.locked_until or (
            self.auto_renew_seconds > 0 and now <= message.received_at + self.auto_renew_seconds
        )

    def _expire_locks(self) -> None:
        if self.sessions:
```

The simulator reproduces the rules the lesson depends on. A message is `LOCKED` with a deadline. A lock is valid until the deadline, or longer if lock renewal is simulated. When the clock passes the deadline the message becomes available again; if it was delivered `max_delivery_count` times it goes to the dead-letter state instead. A late `complete` raises the same error text the real service uses.

```python
    def _release(self, message: _Message) -> None:
        """Make a message available again, or dead-letter it when it was delivered the maximum number of times."""
        if message.delivery_count >= self.max_delivery_count:
            message.state = _State.DEAD
            message.dead_reason = "MaxDeliveryCountExceeded"
            message.dead_description = (
                f"Message could not be consumed after {self.max_delivery_count} delivery attempts."
            )
```

`_release` is the delivery-count rule: ten deliveries and the message is dead-lettered with reason `MaxDeliveryCountExceeded`.

The simulator is a teaching model: it has no message expiry, scheduled messages or duplicate detection, and a session lock does not expire by itself. The first run against Azure is its test.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/servicebus/main.tf`

75 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 16**

```hcl
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
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** **TLS** is the protocol that encrypts a network connection and proves who is on the other end, which is what the `s` in `https` stands for. The server proves its identity with a **certificate**, a signed document that names the server and carries its public key; a client refuses a certificate it cannot trust.

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

**New idea.** A **private endpoint** gives an Azure service (a vault, a storage account) a private IP address inside your subnet, so traffic stays on your private network. For the service's normal name to lead to that private address, a *private DNS zone* (such as `privatelink.vaultcore.azure.net`) must be linked to the network.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_servicebus_namespace" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_servicebus_namespace.this`. A **Service Bus namespace** is the account-like container that holds queues and topics; it has its own host name and settings.
- `#checkov:skip=CKV_AZURE_201:customer-managed keys need the Premium tier; Standard is the cheapest tier that ha`…: A comment of the form `#checkov:skip=RULE:reason` tells the scanner checkov to ignore one rule for this resource and records why. Without the reason the skip is hard to defend in review. Scanner exception for rule `CKV_AZURE_201`: customer-managed keys need the Premium tier; Standard is the cheapest tier that has sessions.
- `#checkov:skip=CKV_AZURE_199:double encryption needs the Premium tier`: Scanner exception for rule `CKV_AZURE_199`: double encryption needs the Premium tier.
- `#checkov:skip=CKV_AZURE_202:the namespace makes no outbound calls, so it needs no identity of its own`: Scanner exception for rule `CKV_AZURE_202`: the namespace makes no outbound calls, so it needs no identity of its own.
- `#checkov:skip=CKV_AZURE_204:private endpoints and network rules need the Premium tier; access is Entra ID only`…: Scanner exception for rule `CKV_AZURE_204`: private endpoints and network rules need the Premium tier; access is Entra ID only (local_auth_enabled = false).
- `name                = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter).
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the namespace).
- `location            = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `sku                 = "Standard" # sessions need Standard or Premium; Standard is the cheaper of the two`: `sku`: The pricing tier / capability level (the SKU) of the service. Here: the text `"Standard"`.
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the namespace and the alert).
- `# Entra ID only: shared access signatures and the connection strings that carry them stop working, so the prod`…: A line starting with `#` (or `//`) is a **comment**: Terraform ignores it; it is there for the reader. Comment for the reader: Entra ID only: shared access signatures and the connection strings that carry them stop working, so the producer
- `# and the worker can authenticate with nothing but their identities.`: Comment for the reader: and the worker can authenticate with nothing but their identities.
- `local_auth_enabled  = false`: `local_auth_enabled`: When `false`, shared access keys are disabled and every client must use an Entra ID token. Here: `false`.
- `minimum_tls_version = "1.2"`: `minimum_tls_version`: The oldest TLS (encryption protocol) version the service accepts. Here: the text `"1.2"`.
- Closing line: `}` ends the block opened above.

**Lines 18 to 32**

```hcl
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
```

**New idea.** A **process** is one running copy of a program. The operating system gives it its own memory and a number, its *pid*. Two processes do not share variables; they cooperate through files, network connections or signals.

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

- `resource "azurerm_servicebus_queue" "this" {`: Declares the resource `azurerm_servicebus_queue.this`. A **Service Bus queue** stores messages until a receiver processes them, with delivery counting, locking and a dead-letter sub-queue.
- `for_each = var.queues`: `for_each` makes one copy of the resource (or module) for each entry of a map or set. Inside, `each.key` is the entry's key and `each.value` its value. Each copy is tracked under its key, so adding or removing one entry touches only that copy. `for_each` is set to the input variable `queues`.
- `name         = each.key`: `name`: The name of this thing in Azure. Here: `each.key`, the key of the entry being repeated.
- `namespace_id = azurerm_servicebus_namespace.this.id`: `namespace_id`: The id of the Service Bus namespace the queue belongs to. Here: the `id` of the resource `azurerm_servicebus_namespace.this`.
- `lock_duration      = each.value.lock_duration`: `lock_duration`: How long a receiver holds a message exclusively after taking it, in ISO 8601 duration form (`PT30S` is 30 seconds). Here: `each.value`, the value of the entry being repeated.
- `max_delivery_count = each.value.max_delivery_count`: `max_delivery_count`: How many times a message is delivered before it is moved to the dead-letter queue. Here: `each.value`, the value of the entry being repeated.
- `requires_session   = each.value.requires_session`: `requires_session`: Whether the queue groups messages into sessions (ordered streams per key). Here: `each.value`, the value of the entry being repeated.
- `# A message that expires unprocessed goes to the dead-letter queue instead of vanishing.`: Comment for the reader: A message that expires unprocessed goes to the dead-letter queue instead of vanishing.
- `dead_lettering_on_message_expiration = true`: `dead_lettering_on_message_expiration`: Whether messages whose time-to-live runs out go to the dead-letter queue instead of vanishing. Here: `true`.
- `default_message_ttl                  = each.value.default_message_ttl`: `default_message_ttl`: How long an undelivered message lives before it expires. Here: `each.value`, the value of the entry being repeated.
- `max_size_in_megabytes                = 1024`: `max_size_in_megabytes`: The most data the queue may hold. Here: the number `1024`.
- Closing line: `}` ends the block opened above.

**Lines 34 to 46**

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

**New idea.** **Log Analytics** is Azure's store for logs and metrics, queried with the Kusto Query Language (KQL). A *diagnostic setting* tells a resource to send its logs there, so that, for example, every refused request to a vault can be found afterwards.

- `resource "azurerm_monitor_diagnostic_setting" "namespace" {`: Declares the resource `azurerm_monitor_diagnostic_setting.namespace`. A **diagnostic setting** tells an Azure resource to send its logs and metrics to a destination, here a Log Analytics workspace.
- `name                       = "to-log-analytics"`: `name`: The name of this thing in Azure. Here: the text `"to-log-analytics"`.
- `target_resource_id         = azurerm_servicebus_namespace.this.id`: `target_resource_id`: The id of the Azure resource whose diagnostics are being routed. Here: the `id` of the resource `azurerm_servicebus_namespace.this`.
- `log_analytics_workspace_id = var.log_analytics_workspace_id`: `log_analytics_workspace_id`: The id of the Log Analytics workspace that receives the data. Here: the input variable `log_analytics_workspace_id` (Workspace that receives the operational logs and metrics).
- `enabled_log {`: Starts the nested `enabled_log` block: Selects one log category to send to the destination.
- `category = "OperationalLogs"`: `category`: The name of one log category to send (for example `AuditEvent`). Here: the text `"OperationalLogs"`.
- `enabled_metric {`: Starts the nested `enabled_metric` block: Selects one metric category to send to the destination.
- `category = "AllMetrics"`: `category`: The name of one metric category to send (for example `AllMetrics`). Here: the text `"AllMetrics"`.
- Closing lines: `}` end the blocks opened above.

**Lines 48 to 64**

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

- `resource "azurerm_monitor_action_group" "dead_letters" {`: Declares the resource `azurerm_monitor_action_group.dead_letters`. An **action group** is a reusable list of who to notify (e-mail addresses) when an alert fires.
- `count = length(var.alert_email_addresses) > 0 ? 1 : 0`: `count = n` makes `n` copies; `count.index` is the number of the current copy (starting at 0). `count = 0` means none, which is how a resource is switched off. `count` is set to the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert). `length(x)` counts the items of a list, map or characters of text.
- `name                = "ag-${var.name}-dead-letters"`: `name`: The name of this thing in Azure. Here: text built from the pieces the input variable `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter). `${...}` inside a quoted string is **interpolation**: Terraform evaluates what is inside and puts its text into the string.
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the namespace).
- `short_name          = "deadltr"`: `short_name`: A short label (up to 12 characters) shown in notifications. Here: the text `"deadltr"`.
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the namespace and the alert).
- `dynamic "email_receiver" {`: A `dynamic` block repeats a nested block once for each entry of a collection (`for_each`); `content { ... }` is the block to repeat, and the loop variable is named after the dynamic block. Repeats the nested block `email_receiver` once for each entry of the collection named by `for_each`.
- `for_each = toset(var.alert_email_addresses)`: `for_each` is set to the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert). `toset(list)` converts a list to a set (no duplicates, no order).
- `content {`: Starts the nested `content` block: The body of the block repeated by the `dynamic` block.
- `name                    = "mail-${index(var.alert_email_addresses, email_receiver.value)}"`: `name`: The name of this thing in Azure. Here: text built from the pieces the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert). `index(list, value)` is the position of the value in the list.
- `email_address           = email_receiver.value`: `email_address`: The e-mail address to notify. Here: `email_receiver.value`.
- `use_common_alert_schema = true`: `use_common_alert_schema`: Whether alert e-mails use Azure's common alert format. Here: `true`.
- Closing lines: `}` end the blocks opened above.

**Lines 66 to 90**

```hcl
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
```

- `# The runbook's third signal: a dead-letter count above zero means a command that could never succeed is waiti`…: Comment for the reader: The runbook's third signal: a dead-letter count above zero means a command that could never succeed is waiting.
- `resource "azurerm_monitor_metric_alert" "dead_letters" {`: Declares the resource `azurerm_monitor_metric_alert.dead_letters`. A **metric alert** watches a numeric metric of a resource and fires its action group when a rule is true.
- `count = length(var.alert_email_addresses) > 0 ? 1 : 0`: `count` is set to the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert).
- `name                = "alert-${var.name}-dead-letters"`: `name`: The name of this thing in Azure. Here: text built from the pieces the input variable `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter).
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the namespace).
- `scopes              = [azurerm_servicebus_namespace.this.id]`: `scopes`: The resources the rule watches. Here: the `id]` of the resource `azurerm_servicebus_namespace.this`.
- `description         = "At least one message is in a dead-letter queue. Read it with order-dlq (docs/RUNBOOK.md`…: `description`: A human-readable explanation. Here: the text `"At least one message is in a dead-letter queue. Read it with order-dlq (docs/RUNBOOK.md)."`.
- `severity            = 2`: `severity`: The importance of the alert, 0 (critical) to 4 (verbose). Here: the number `2`.
- `frequency           = "PT1M"`: `frequency`: How often the rule is evaluated. Here: the text `"PT1M"`.
- `window_size         = "PT5M"`: `window_size`: The length of time over which the metric is evaluated. Here: the text `"PT5M"`.
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the namespace and the alert).
- `criteria {`: Starts the nested `criteria` block: The rule the alert evaluates.
- `metric_namespace = "Microsoft.ServiceBus/namespaces"`: `metric_namespace`: The group the metric belongs to. Here: the text `"Microsoft.ServiceBus/namespaces"`.
- `metric_name      = "DeadletteredMessages"`: `metric_name`: The name of the metric being watched. Here: the text `"DeadletteredMessages"`.
- `aggregation      = "Maximum"`: `aggregation`: How samples within the window are combined (`Total`, `Average`...). Here: the text `"Maximum"`.
- `operator         = "GreaterThan"`: `operator`: How the metric is compared with the threshold (for example `GreaterThan`). Here: the text `"GreaterThan"`.
- `threshold        = 0`: `threshold`: The value of the metric at which the alert fires. Here: the number `0`.
- `action {`: Starts the nested `action` block: What the alert does when it fires.
- `action_group_id = azurerm_monitor_action_group.dead_letters[0].id`: `action_group_id`: The id of the action group to notify. Here: the resource `azurerm_monitor_action_group.dead_letters`.
- Closing lines: `}` end the blocks opened above.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/environments/dev/tests/dev.tftest.hcl` | 5, 10, 34, 41, 80, 124, 138, 191 | [terraform.md](terraform.md) |
| `infra/environments/dev/main.tf` | 32, 38, 56, 62, 103 to 104, 152 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/outputs.tf` | 3, 8, 12 to 13, 18, 23 | [terraform.md](terraform.md) |
| `tests/unit/infrastructure/test_servicebus_adapter.py` | 1, 7 to 8, 17, 179, 234 | [pytest.md](pytest.md) |
| `infra/environments/dev/outputs.tf` | 7 to 8, 11 to 13, 18 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/tests/servicebus.tftest.hcl` | 18, 23, 32, 37, 46 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/tests/role_assignments.tftest.hcl` | 7, 22, 34, 66 | [terraform.md](terraform.md) |
| `src/order_worker/infrastructure/servicebus.py` | 1, 7, 16, 109 | [azure-servicebus.md](azure-servicebus.md) |
| `pyproject.toml` | 8, 15, 67 | [pyproject-toml.md](pyproject-toml.md) |
| `infra/modules/role_assignments/variables.tf` | 31 to 32 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/tests/worker_app.tftest.hcl` | 15, 105 | [terraform.md](terraform.md) |
| `src/order_worker/infrastructure/simulation.py` | 1, 90 | [python.md](python.md) |
| `infra/modules/worker_app/main.tf` | 17 | [azure-container-apps.md](azure-container-apps.md) |
| `scripts/env.sh` | 7 | [bash.md](bash.md) |
| `scripts/provision.sh` | 2 | [bash.md](bash.md) |
| `scripts/show-queues.sh` | 12 | [bash.md](bash.md) |
| `scripts/teardown.sh` | 15 | [bash.md](bash.md) |
| `src/order_worker/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/application/ports.py` | 12 | [python.md](python.md) |
| `src/order_worker/infrastructure/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/infrastructure/settings.py` | 44 | [python.md](python.md) |
| `src/order_worker/infrastructure/wiring.py` | 5 | [python.md](python.md) |
| `src/order_worker/interfaces/simulate_cli.py` | 1 | [python.md](python.md) |
| `tests/integration/test_azure_live.py` | 1 | [pytest.md](pytest.md) |
| `tests/unit/infrastructure/test_settings_logging_clock_shutdown.py` | 16 | [pytest.md](pytest.md) |
| `tests/unit/infrastructure/test_simulation.py` | 1 | [pytest.md](pytest.md) |
| `tests/unit/interfaces/test_clis.py` | 45 | [pytest.md](pytest.md) |

## Try it yourself

Run the duplicates demo and read the three ledger totals.

```bash
make demo-duplicates 2>&1 | grep -E 'duplicates:|ledger:|OK|MISMATCH: expected' | head -12
```

You should see something like this:

```text
duplicates: mode=naive lock renewal=0s, 30 s lock, every 10th seq takes 45 s
  ledger: 1100|11000.0   highest delivery count: 2   dead letters: 0
  MISMATCH: expected 1000 rows, found 1100
  MISMATCH: expected a total of 10000.0, found 11000.0
duplicates: mode=idempotent lock renewal=0s, 30 s lock, every 10th seq takes 45 s
  ledger: 1000|10000.0   highest delivery count: 2   dead letters: 0
  OK: exactly the expected end state
duplicates: mode=idempotent lock renewal=300s, 30 s lock, every 10th seq takes 45 s
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

Run the ordering demo with and without sessions.

```bash
make demo-sessions 2>&1 | grep -E 'ordering|ledger:|MISMATCH: out of order|OK' | head -8
```

You should see something like this:

```text
.venv/bin/order-simulate --expect dirty ordering
ordering: 4 workers, sessions=off, worker 0 stalls on o-c01-010
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  MISMATCH: out of order: c01: seq 10 applied after seq 16
.venv/bin/order-simulate --expect clean ordering --sessions
ordering: 4 workers, sessions=on, worker 0 stalls on o-c01-010
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

Run the poison and replay demo.

```bash
make demo-poison 2>&1 | tail -9
```

You should see something like this:

```text
poison: one command with amount 'abc', then the replay tool
  log  dead-letter o-bad: InvalidAmount: amount is not a number
  dead letter: o-bad  reason=InvalidAmount  description="amount is not a number"
  ledger rows while the poison waits: 1000 (the other commands kept flowing)
  replay: fixed=1; a second replay finds fixed=0
  rows for o-bad after the replay: 1
  handled=1 applied=1 skipped_duplicates=0 dead_lettered=0 lock_lost=0
  ledger: 1001|10010.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

## Mistakes people make

- Assuming exactly-once delivery.
- Creating the queue without sessions and trying to enable them later: it cannot be changed, so a second queue is created.
- Using the namespace-wide owner role for the worker.
- Choosing a lock duration shorter than normal processing time without renewal.
- Leaving a dead-letter queue unmonitored. An alert rule watches its count here.

## Check yourself

1. **What is a dead-letter queue?**
   Answer: A sub-queue holding messages that could not be processed.

2. **What happens after the maximum delivery count?**
   Answer: The broker moves the message to the dead-letter queue.

3. **Can sessions be turned on for an existing queue?**
   Answer: No.

4. **What does `local_auth_enabled = false` do?**
   Answer: Turns off shared access keys, leaving only Entra ID access.

5. **Which role lets a worker receive but not send?**
   Answer: `Azure Service Bus Data Receiver`.

## Further reading

- Service Bus queues: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-queues-topics-subscriptions
- Dead-letter queues: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-dead-letter-queues
- Message sessions: https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-sessions
- Pricing tiers: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-premium-messaging
