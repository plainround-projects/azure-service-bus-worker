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
