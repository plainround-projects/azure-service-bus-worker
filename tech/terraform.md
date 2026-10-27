# Terraform

*Defines every Azure resource of the lesson as code. Pinned here: Terraform 1.17.0 (CI pins it); needs 1.9 or newer.*

## What it is

Terraform is a tool that creates and changes cloud resources from text files. You describe the resources you want in the **HashiCorp Configuration Language (HCL)**; Terraform works out what exists, what must change, and makes the changes. The files are the record of your infrastructure, and they live in Git like code.

## Why this repository uses it

Cloud projects must hold their infrastructure as code that can be validated without a subscription. `infra/` is the lesson's resource list: namespace, queues, identities, roles, registry, worker app, alert and budget.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/` | Seven reusable modules, each with variables, outputs, a README and tests. |
| `infra/environments/dev/` | The composition. |
| `infra/environments/dev/tests/dev.tftest.hcl` | Applies the composition against a mocked provider. |
| `Makefile` | `make validate`, `make tf-test`. |

## How it works underneath

A **resource** block says "this thing should exist" (`resource "azurerm_key_vault" "this" { ... }`). A **variable** is an input, an **output** a result, a **local** a named expression. A **module** is a folder of Terraform files used like a function: `module "x" { source = "../modules/y" ... }`.

`terraform init` downloads the **providers** (plugins that talk to a cloud) named in `required_providers` and records their exact versions and hashes in `.terraform.lock.hcl`. `terraform validate` checks the syntax and that every argument exists and has the right type. `terraform plan` compares the files with the **state** (a record of what Terraform made) and the real cloud and prints what would change. `terraform apply` makes the changes. `terraform destroy` removes everything in the state.

`terraform test` runs files ending in `.tftest.hcl`. Each `run` block plans or applies the configuration and checks `assert` conditions. A `mock_provider` replaces a real provider with a fake that invents values, so tests need no cloud account. `expect_failures` says a variable validation or a precondition is meant to fail.

Terraform decides the order of work from references: if one resource uses another's attribute, the other is created first. `depends_on` adds an order that references do not show. `count` and `for_each` make several copies of a resource or module.

## Walkthrough of this repository's use

### A resource and a local

```hcl
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}
```

`resource "type" "name" { ... }` declares one thing to create. The arguments make five lowercase letters and digits that make globally unique names (the namespace and the registry).

```hcl
  names = {
    resource_group  = "rg-${var.name_prefix}"
    workspace       = "law-${var.name_prefix}"
    worker_identity = "id-${var.name_prefix}-worker"
    pull_identity   = "id-${var.name_prefix}-pull"
    namespace       = "sb-${var.name_prefix}-${local.suffix}"
    registry        = "acr${var.name_prefix}${local.suffix}"
    environment     = "cae-${var.name_prefix}"
    worker          = "ca-${var.name_prefix}-worker"
    budget          = "budget-${var.name_prefix}"
  }
```

A `locals` map builds every name in one place: `sb-${var.name_prefix}-${local.suffix}` puts variables into text.

### The queues are data

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

A module call with an input map: `orders = {}` takes all the defaults (30-second lock, 10 deliveries); `orders-sessions = { requires_session = true }` overrides one.

### `for` expressions build the role list

```hcl
  worker_assignments = {
    for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {
      principal_id = module.worker_identity.principal_id
      role         = "Azure Service Bus Data Receiver"
      scope        = queue_id
    }
  }
```

`{ for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {...} }` creates one map entry per queue, keyed by a stable name.

### Variables with checks

```hcl
  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$", var.name))
    error_message = "A namespace name has 6 to 50 characters, starts with a letter, ends with a letter or digit and holds letters, digits and hyphens."
  }
```

A `validation` is a condition plus an error message. `can(regex(...))` is true when the pattern matches. `alltrue([for ...])` requires every queue to pass.

### Conditional creation

```hcl
module "worker_app" {
  source = "../../modules/worker_app"
  count  = var.deploy_worker ? 1 : 0

  name                       = local.names.worker
  environment_name           = local.names.environment
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = module.log_analytics.id
  image                      = coalesce(var.image, "unused.azurecr.io/unused:0")
  worker_identity_id         = module.worker_identity.id
  pull_identity_id           = module.pull_identity.id
  registry_server            = module.registry.login_server
  tags                       = local.tags

  # Addresses, names and tuning knobs. Nothing here is a secret, and there is no connection string to put here.
  env = {
    AZURE_CLIENT_ID      = module.worker_identity.client_id
    SB_NAMESPACE         = module.servicebus.fully_qualified_namespace
    SB_QUEUE             = var.worker_queue
    USE_SESSIONS         = var.worker_use_sessions ? "1" : "0"
    MODE                 = var.worker_mode
    LOCK_RENEWAL_SECONDS = tostring(var.worker_lock_renewal_seconds)
    SLOW_EVERY           = tostring(var.worker_slow_every)
    HEALTH_PORT          = "8080"
    LEDGER_PATH          = "/data/orders.db"
    SQL_DIR              = "/app/sql"
    LOG_LEVEL            = "INFO"
  }

  # The identity must hold its role before the worker starts, or its first receive is a denial.
  depends_on = [module.role_assignments]
}
```

`count = var.deploy_worker ? 1 : 0` creates the worker only in phase two, after the image exists. `depends_on` makes the app wait for its role assignments.

### Tests

```hcl
run "the_worker_holds_only_data_receiver_one_per_queue_and_never_the_owner_role" {
  command = apply

  assert {
    condition     = length(output.worker_role_assignments) == 2
    error_message = "one Data Receiver assignment per queue and nothing else"
  }

  assert {
    condition     = alltrue([for assignment in output.worker_role_assignments : assignment.role == "Azure Service Bus Data Receiver"])
    error_message = "the worker may only receive"
  }

  assert {
    condition = toset([for assignment in output.worker_role_assignments : assignment.scope]) == toset([
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders",
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions",
    ])
    error_message = "each assignment must be scoped to one queue, not the namespace or the group"
  }
}

run "the_pull_identity_reads_the_registry_and_nothing_else" {
  command = apply

  assert {
    condition     = length([for assignment in module.role_assignments.assignments : assignment if assignment.principal_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]) == 1
    error_message = "the pull identity holds one role"
  }
}
```

A `run` block applies the composition against the mock provider and checks each `assert`. Here: two assignments for the worker, all Data Receiver, each scoped to one queue's id. `expect_failures = [var.image]` in other runs says a validation is meant to fail.

## Try it yourself

Check the syntax and every argument.

```bash
cd infra/environments/dev && terraform init -backend=false -input=false >/dev/null && terraform validate
```

You should see something like this:

```text
Success! The configuration is valid.
```

Plan and apply the composition against the mock.

```bash
cd infra/environments/dev && terraform test 2>&1 | tail -5
```

You should see something like this:

```text
run "names_are_built_from_the_prefix_and_suffix_and_tagged"... pass
tests/dev.tftest.hcl... tearing down
tests/dev.tftest.hcl... pass

Success! 10 passed, 0 failed.
```

Check formatting.

```bash
terraform fmt -check -recursive infra && echo formatted
```

You should see something like this:

```text
formatted
```

Check the version.

```bash
terraform version | head -1
```

You should see something like this:

```text
Terraform v1.17.0
```

## Mistakes people make

- Committing state or `.tfvars` files that hold ids or secrets. Here they are git-ignored; only the examples and the phase files (no ids) are committed.
- Putting a secret into a resource: it is written to the state in clear text. The secret in these repositories is set with the CLI and never enters Terraform.
- Running `apply` without reading the plan.
- Editing resources in the portal and not in the files, causing drift. The next plan shows the difference.
- Using wide scopes or owner roles in role assignments. The role module here refuses them.

## Check yourself

1. **What does `terraform init` do?**
   Answer: Downloads the providers and writes the lock file.

2. **What is the state?**
   Answer: Terraform's record of the resources it created.

3. **What is a module?**
   Answer: A folder of Terraform files used like a function with inputs and outputs.

4. **How does `terraform test` work without a cloud account?**
   Answer: A `mock_provider` supplies invented values for every resource.

5. **What does `expect_failures` check?**
   Answer: That a validation or precondition fails, as intended.

## Further reading

- Terraform language: https://developer.hashicorp.com/terraform/language
- Tests: https://developer.hashicorp.com/terraform/language/tests
- CLI (1.17 is pinned in CI): https://developer.hashicorp.com/terraform/cli
