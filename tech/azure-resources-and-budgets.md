# Resource groups, tags, providers and the budget

*The scope of the lesson and a spending alert. Pinned here: azurerm_resource_group, azurerm_consumption_budget_subscription.*

## What it is

Azure organizes everything in a hierarchy. A **subscription** is the billing container. A **resource group** is a folder-like grouping of resources that share a life cycle: deleting the group deletes everything in it. **Tags** are name-value labels on resources. A **budget** is a spending limit on the subscription that sends emails when actual spend passes chosen percentages.

## Why this repository uses it

A Standard namespace bills by the hour whether or not a message is sent, so the project has a budget and a one-group clean-up.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/environments/dev/main.tf` | The resource group, tags and budget call. |
| `infra/modules/budget/` | The budget. |
| `scripts/provision.sh` | Registers providers. |
| `scripts/teardown.sh` | Destroys and checks the group. |

## How it works underneath

Resource names have rules (length, characters, global uniqueness for names that become host names). Each kind of resource belongs to a **resource provider** such as `Microsoft.KeyVault`; a provider must be **registered** in a subscription before you create its resources. Register once with `az provider register`.

A budget is a subscription-level resource, so deleting a resource group does not remove it. Azure requires its start date to be the first day of a month. Budget alerts are based on actual cost that Azure computes with a delay, so they warn; they do not stop spending.

## Walkthrough of this repository's use

```hcl
resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}
```

One group, `rg-orders`, with the standard tags.

```hcl
resource "azurerm_consumption_budget_subscription" "this" {
  name            = var.name
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.amount
  time_grain      = "Monthly"

  time_period {
    start_date = var.start_date
  }

  dynamic "notification" {
    for_each = toset(var.thresholds_percent)
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.contact_emails
    }
  }
}
```

A monthly budget with a notification at each threshold (80 and 100 percent of actual spend). `start_date` must be the first of a month.

```bash
terraform -chdir="$TF_DIR" destroy -input=false $AUTO_APPROVE
log "resource group $RG exists? -> $(az group exists --name "$RG")"
log "a Service Bus namespace is deleted at once (it has no soft delete); the Standard tier bills by the hour until then"
```

`terraform destroy` removes the budget as well, which deleting the group alone would not (a budget belongs to the subscription). A Service Bus namespace has no soft delete, so it is gone at once.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/budget/main.tf`

19 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 21**

```hcl
resource "azurerm_consumption_budget_subscription" "this" {
  name            = var.name
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.amount
  time_grain      = "Monthly"

  time_period {
    start_date = var.start_date
  }

  dynamic "notification" {
    for_each = toset(var.thresholds_percent)
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.contact_emails
    }
  }
}
```

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** An Azure **budget** watches the spending of a subscription and e-mails people when it passes a threshold such as 80 or 100 percent. It alerts; it does not stop anything from running.

**New idea.** A **GUID** (or UUID) is a 128-bit identifier written as 32 hexadecimal digits in groups, such as `00000000-0000-0000-0000-000000000000`. Azure uses them for subscriptions, tenants and identities. The all-zero value in examples is a placeholder, not a real id.

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

- `resource "azurerm_consumption_budget_subscription" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_consumption_budget_subscription.this`. A **budget** watches spending on a subscription and sends an e-mail when a threshold is crossed. It alerts; it does not stop spending.
- `name            = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Budget name).
- `subscription_id = "/subscriptions/${var.subscription_id}"`: `subscription_id`: The id of the Azure subscription (the billing container) to work in. Here: text built from the pieces the input variable `subscription_id` (Subscription GUID the budget watches). `${...}` inside a quoted string is **interpolation**: Terraform evaluates what is inside and puts its text into the string.
- `amount          = var.amount`: `amount`: The budget amount in the account's currency. Here: the input variable `amount` (Monthly amount in the billing currency).
- `time_grain      = "Monthly"`: `time_grain`: How often the budget resets (`Monthly`). Here: the text `"Monthly"`.
- `time_period {`: Starts the nested `time_period` block: The dates the budget applies.
- `start_date = var.start_date`: `start_date`: The first day the budget applies. Here: the input variable `start_date` (First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month).
- `dynamic "notification" {`: A `dynamic` block repeats a nested block once for each entry of a collection (`for_each`); `content { ... }` is the block to repeat, and the loop variable is named after the dynamic block. Repeats the nested block `notification` once for each entry of the collection named by `for_each`.
- `for_each = toset(var.thresholds_percent)`: `for_each` makes one copy of the resource (or module) for each entry of a map or set. Inside, `each.key` is the entry's key and `each.value` its value. Each copy is tracked under its key, so adding or removing one entry touches only that copy. `for_each` is set to the input variable `thresholds_percent` (Actual-spend percentages that send an alert). `toset(list)` converts a list to a set (no duplicates, no order).
- `content {`: Starts the nested `content` block: The body of the block repeated by the `dynamic` block.
- `enabled        = true`: `enabled`: Whether the setting is switched on. Here: `true`.
- `threshold      = notification.value`: `threshold`: The percentage of the budget at which the e-mail is sent. Here: `notification.value`.
- `operator       = "GreaterThan"`: `operator`: How the spend is compared with the threshold. Here: the text `"GreaterThan"`.
- `threshold_type = "Actual"`: `threshold_type`: Whether the threshold is measured against `Actual` spending or `Forecasted` spending. Here: the text `"Actual"`.
- `contact_emails = var.contact_emails`: `contact_emails`: The e-mail addresses that receive the alert. Here: the input variable `contact_emails` (Addresses that receive the alerts).
- Closing lines: `}` end the blocks opened above.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/environments/dev/main.tf` | 19, 70, 80 to 81, 89 to 90, 98 to 99, 107 to 108, 123 to 124, 140 to 141, 168 to 176 | [terraform.md](terraform.md) |
| `infra/environments/dev/variables.tf` | 124 to 125, 130 to 131, 136 to 137, 142 to 143 | [terraform.md](terraform.md) |
| `infra/environments/dev/tests/dev.tftest.hcl` | 177, 181, 184, 191, 196 | [terraform.md](terraform.md) |
| `infra/modules/budget/tests/budget.tftest.hcl` | 4, 15 to 16, 30 | [terraform.md](terraform.md) |
| `scripts/provision.sh` | 3, 23, 30 to 31 | [bash.md](bash.md) |
| `infra/environments/dev/terraform.tfvars.example` | 17 to 19 | [terraform.md](terraform.md) |
| `infra/modules/budget/variables.tf` | 7, 27, 42 | [terraform.md](terraform.md) |
| `infra/environments/dev/outputs.tf` | 3 | [terraform.md](terraform.md) |
| `infra/modules/budget/outputs.tf` | 3 | [terraform.md](terraform.md) |
| `scripts/teardown.sh` | 2 | [bash.md](bash.md) |
| `src/order_worker/application/run_worker.py` | 50 | [python.md](python.md) |
| `tests/unit/application/test_run_worker.py` | 49 | [pytest.md](pytest.md) |

## Try it yourself

Run the budget tests.

```bash
cd infra/modules/budget && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -4
```

You should see something like this:

```text
tests/budget.tftest.hcl... tearing down
tests/budget.tftest.hcl... pass

Success! 3 passed, 0 failed.
```

## Mistakes people make

- Forgetting that deleting the resource group does not delete the subscription-level budget.
- A budget start date that is not the first of a month.
- Skipping provider registration on a new subscription.
- Unlabeled resources. Every resource here gets the same tags.
- Believing a budget caps spending; it only notifies.

## Check yourself

1. **What happens when you delete a resource group?**
   Answer: Every resource in it is deleted.

2. **Why register resource providers?**
   Answer: A subscription can create resources of a kind only after its provider is registered.

3. **What must a budget's start date be?**
   Answer: The first day of a month.

4. **Does a budget stop spending?**
   Answer: No; it sends alerts.

5. **What are tags for?**
   Answer: Labelling resources for ownership, cost and search.

## Further reading

- Resource groups: https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/manage-resource-groups-portal
- Budgets: https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets
- Naming rules: https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-name-rules
