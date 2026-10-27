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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/environments/dev/backend.hcl.example`

7 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 3**

```text
# Remote state in a storage account you create once, outside this project, with Entra authentication:
#   terraform init -backend-config=backend.hcl
resource_group_name  = "rg-terraform-state"
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** **Azure Blob Storage** stores files (*blobs*) in a *storage account*. Blobs live in *containers*, which work like top-level folders, and each blob is addressed by account, container and name. (This "container" is not a Docker container.)

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

- `# Remote state in a storage account you create once, outside this project, with Entra authentication:`: Comment. By default each environment keeps its Terraform state in a local file, which is fine for practice. For shared work the state belongs in a storage account, so everyone sees the same record of what exists. The next line shows the command that uses this file.
- `#   terraform init -backend-config=backend.hcl`: Comment showing the command: `terraform init -backend-config=backend.hcl` initializes Terraform and fills the (empty) `backend "azurerm" {}` block in `versions.tf` with the settings from this file.
- `resource_group_name  = "rg-terraform-state"`: The resource group that holds the state storage account. This account is created once, by hand, outside this project, so destroying the project can never destroy its own state.

**Lines 4 to 7**

```text
storage_account_name = "stterraformstate00000"
container_name       = "tfstate"
key                  = "azure-service-bus-worker/dev.tfstate"
use_azuread_auth     = true
```

- `storage_account_name = "stterraformstate00000"`: The name of the storage account that holds the state. The value is a placeholder; replace it with the real name.
- `container_name       = "tfstate"`: The blob container inside that account that holds the state files.
- `key                  = "azure-service-bus-worker/dev.tfstate"`: The name of the blob (file) for this environment's state; the project and environment name make it unique within the container.
- `use_azuread_auth     = true`: `true` makes Terraform sign in to the storage account with the Entra ID login of the person running it, instead of the account's access key, which fits the project's no-shared-keys rule.

#### `infra/environments/dev/main.tf`

150 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```hcl
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}
```

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** A **container registry** is a server that stores container images under names and version tags. **Azure Container Registry (ACR)** is Azure's; a service pulls an image from it using an identity that holds the `AcrPull` role.

- `resource "random_string" "suffix" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `random_string.suffix`. Creates a random text once and keeps it in the state, so the same value is reused on every later run. It supplies the short suffix that makes globally unique Azure names (Key Vault, storage account, container registry).
- `length  = 5`: `length`: How many characters long the random text is. Here: the number `5`.
- `upper   = false`: `upper`: Whether the random text may contain uppercase letters. Here: `false`.
- `special = false`: `special`: Whether the random text may contain punctuation characters. Here: `false`.
- Closing line: `}` ends the block opened above.

**Lines 7 to 34**

```hcl
locals {
  suffix = coalesce(var.suffix, random_string.suffix.result)

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

  tags = merge(
    {
      project     = "azure-service-bus-worker"
      environment = var.environment
      managed_by  = "terraform"
      owner       = "sumit-srivastava"
    },
    var.tags,
  )

  queue_ids = module.servicebus.queue_ids

  # The one place that decides who may do what. Every scope is one queue; nobody holds the namespace-wide owner role.
```

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** An Azure **budget** watches the spending of a subscription and e-mails people when it passes a threshold such as 80 or 100 percent. It alerts; it does not stop anything from running.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

- `locals {`: A `locals` block defines named values that exist only inside this folder. Each is read as `local.<name>`. They avoid repeating an expression and give a calculation a name. Starts a group of named local values.
- `suffix = coalesce(var.suffix, random_string.suffix.result)`: Defines the local value `suffix` as the input variable `suffix` (Characters that make the namespace and registry names globally unique. Leave null to generate five), the `result` of the resource `random_string.suffix`. `coalesce(a, b, ...)` returns the first argument that is not `null` or empty.
- `names = {`: Defines the local value `names` as a group of named values that follows.
- `resource_group  = "rg-${var.name_prefix}"`: Entry `resource_group`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only). `${...}` inside a quoted string is **interpolation**: Terraform evaluates what is inside and puts its text into the string.
- `workspace       = "law-${var.name_prefix}"`: Entry `workspace`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `worker_identity = "id-${var.name_prefix}-worker"`: Entry `worker_identity`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `pull_identity   = "id-${var.name_prefix}-pull"`: Entry `pull_identity`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `namespace       = "sb-${var.name_prefix}-${local.suffix}"`: Entry `namespace`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only), the local value `suffix`.
- `registry        = "acr${var.name_prefix}${local.suffix}"`: Entry `registry`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only), the local value `suffix`.
- `environment     = "cae-${var.name_prefix}"`: Entry `environment`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `worker          = "ca-${var.name_prefix}-worker"`: Entry `worker`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `budget          = "budget-${var.name_prefix}"`: Entry `budget`: text built from the pieces the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only).
- `tags = merge(`: Defines the local value `tags` as `merge(`. `merge(a, b, ...)` combines maps into one; for a key present in several, the later map wins.
- `{`: Opens a nested value.
- `project     = "azure-service-bus-worker"`: Entry `project`: the text `"azure-service-bus-worker"`.
- `environment = var.environment`: Entry `environment`: the input variable `environment` (Environment name, used in tags).
- `managed_by  = "terraform"`: Entry `managed_by`: the text `"terraform"`.
- `owner       = "sumit-srivastava"`: Entry `owner`: the text `"sumit-srivastava"`.
- `var.tags,`: Item: the input variable `tags` (Extra tags merged into the standard ones).
- `queue_ids = module.servicebus.queue_ids`: Defines the local value `queue_ids` as the output `queue_ids` of the module `servicebus`.
- `# The one place that decides who may do what. Every scope is one queue; nobody holds the namespace-wide owner `…: Comment for the reader: The one place that decides who may do what. Every scope is one queue; nobody holds the namespace-wide owner role.
- Closing lines: `}`, `},`, `)` end the blocks opened above.

**Lines 35 to 49**

```hcl
  worker_assignments = {
    for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {
      principal_id = module.worker_identity.principal_id
      role         = "Azure Service Bus Data Receiver"
      scope        = queue_id
    }
  }

  pull_assignments = {
    pull_reads_registry = {
      principal_id = module.pull_identity.principal_id
      role         = "AcrPull"
      scope        = module.registry.id
    }
  }
```

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

**New idea.** **Azure role-based access control (RBAC)** decides who may do what. A *role* is a named bundle of permissions (for example "Key Vault Secrets User" may read secrets), a *scope* is where the grant applies (one resource, a resource group, a whole subscription), and a *role assignment* connects an identity, a role and a scope. The smaller the scope, the less a leaked identity can do.

- `worker_assignments = {`: Defines the local value `worker_assignments` as a group of named values that follows.
- `for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {`: A `for` expression builds a map or list from another collection: `{ for key, value in things : key => f(value) if condition }` means "for every entry that passes the `if`, make this new entry". Part of a `for` expression: `for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {`.
- `principal_id = module.worker_identity.principal_id`: Entry `principal_id`: the output `principal_id` of the module `worker_identity`.
- `role         = "Azure Service Bus Data Receiver"`: Entry `role`: the text `"Azure Service Bus Data Receiver"`.
- `scope        = queue_id`: Entry `scope`: `queue_id`.
- `pull_assignments = {`: Defines the local value `pull_assignments` as a group of named values that follows.
- `pull_reads_registry = {`: Entry `pull_reads_registry`: a group of named values that follows.
- `principal_id = module.pull_identity.principal_id`: Entry `principal_id`: the output `principal_id` of the module `pull_identity`.
- `role         = "AcrPull"`: Entry `role`: the text `"AcrPull"`.
- `scope        = module.registry.id`: Entry `scope`: the output `id` of the module `registry`.
- Closing lines: `}` end the blocks opened above.

**Lines 51 to 68**

```hcl
  operator_assignments = merge([
    for queue_name, queue_id in local.queue_ids : {
      "operator_sends_${queue_name}" = {
        principal_id   = var.operator_object_id
        principal_type = "User"
        role           = "Azure Service Bus Data Sender"
        scope          = queue_id
      }
      "operator_receives_${queue_name}" = {
        principal_id   = var.operator_object_id
        principal_type = "User"
        role           = "Azure Service Bus Data Receiver"
        scope          = queue_id
      }
    }
    if var.operator_object_id != null
  ]...)
}
```

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

- `operator_assignments = merge([`: Defines the local value `operator_assignments` as `merge([`.
- `for queue_name, queue_id in local.queue_ids : {`: Part of a `for` expression: `for queue_name, queue_id in local.queue_ids : {`.
- `"operator_sends_${queue_name}" = {`: Item: the text `"operator_sends_${queue_name}" = {`.
- `principal_id   = var.operator_object_id`: Entry `principal_id`: the input variable `operator_object_id` (Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing).
- `principal_type = "User"`: Entry `principal_type`: the text `"User"`.
- `role           = "Azure Service Bus Data Sender"`: Entry `role`: the text `"Azure Service Bus Data Sender"`.
- `scope          = queue_id`: Entry `scope`: `queue_id`.
- `"operator_receives_${queue_name}" = {`: Item: the text `"operator_receives_${queue_name}" = {`.
- `principal_id   = var.operator_object_id`: Entry `principal_id`: the input variable `operator_object_id` (Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing).
- `principal_type = "User"`: Entry `principal_type`: the text `"User"`.
- `role           = "Azure Service Bus Data Receiver"`: Entry `role`: the text `"Azure Service Bus Data Receiver"`.
- `scope          = queue_id`: Entry `scope`: `queue_id`.
- `if var.operator_object_id != null`: Part of a `for` expression: `if var.operator_object_id != null`.
- `]...)`: Item: `]...)`.
- Closing lines: `}` end the blocks opened above.

**Lines 70 to 74**

```hcl
resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}
```

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_resource_group" "this" {`: Declares the resource `azurerm_resource_group.this`. A **resource group** is the folder-like container every other Azure resource of this project lives in. Deleting the group deletes everything in it, which is how the project is torn down in one step.
- `name     = local.names.resource_group`: `name`: The name of this thing in Azure. Here: the local value `names` field `resource_group`.
- `location = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `tags     = local.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the local value `tags`.
- Closing line: `}` ends the block opened above.

**Lines 76 to 83**

```hcl
module "log_analytics" {
  source = "../../modules/log_analytics"

  name                = local.names.workspace
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}
```

- `module "log_analytics" {`: A `module` block calls another folder of Terraform files as a reusable unit. `source` is the folder; the other lines pass values into the module's input variables. The module's outputs come back as `module.<name>.<output>`. Calls a module and names this use of it `log_analytics`; its outputs are read as `module.log_analytics.<output>`.
- `source = "../../modules/log_analytics"`: `source` is the folder holding the module's code: the text `"../../modules/log_analytics"`.
- `name                = local.names.workspace`: Passes `name` (Workspace name, for example law-orders): the local value `names` field `workspace`.
- `resource_group_name = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds the workspace): the `name` of the resource `azurerm_resource_group.this`.
- `location            = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `tags                = local.tags`: Passes `tags` (Tags applied to the workspace): the local value `tags`.
- Closing line: `}` ends the block opened above.

**Lines 85 to 92**

```hcl
module "worker_identity" {
  source = "../../modules/user_assigned_identity"

  name                = local.names.worker_identity
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}
```

- `module "worker_identity" {`: Calls a module and names this use of it `worker_identity`; its outputs are read as `module.worker_identity.<output>`.
- `source = "../../modules/user_assigned_identity"`: `source` is the folder holding the module's code: the text `"../../modules/user_assigned_identity"`.
- `name                = local.names.worker_identity`: Passes `name` (Identity name, for example id-orders-worker): the local value `names` field `worker_identity`.
- `resource_group_name = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds the identity): the `name` of the resource `azurerm_resource_group.this`.
- `location            = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `tags                = local.tags`: Passes `tags` (Tags applied to the identity): the local value `tags`.
- Closing line: `}` ends the block opened above.

**Lines 94 to 101**

```hcl
module "pull_identity" {
  source = "../../modules/user_assigned_identity"

  name                = local.names.pull_identity
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}
```

- `module "pull_identity" {`: Calls a module and names this use of it `pull_identity`; its outputs are read as `module.pull_identity.<output>`.
- `source = "../../modules/user_assigned_identity"`: `source` is the folder holding the module's code: the text `"../../modules/user_assigned_identity"`.
- `name                = local.names.pull_identity`: Passes `name` (Identity name, for example id-orders-worker): the local value `names` field `pull_identity`.
- `resource_group_name = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds the identity): the `name` of the resource `azurerm_resource_group.this`.
- `location            = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `tags                = local.tags`: Passes `tags` (Tags applied to the identity): the local value `tags`.
- Closing line: `}` ends the block opened above.

**Lines 103 to 117**

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

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

- `module "servicebus" {`: Calls a module and names this use of it `servicebus`; its outputs are read as `module.servicebus.<output>`.
- `source = "../../modules/servicebus"`: `source` is the folder holding the module's code: the text `"../../modules/servicebus"`.
- `name                       = local.names.namespace`: Passes `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter): the local value `names` field `namespace`.
- `resource_group_name        = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds the namespace): the `name` of the resource `azurerm_resource_group.this`.
- `location                   = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `log_analytics_workspace_id = module.log_analytics.id`: Passes `log_analytics_workspace_id` (Workspace that receives the operational logs and metrics): the output `id` of the module `log_analytics`.
- `alert_email_addresses      = var.alert_email_addresses`: Passes `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert): the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert).
- `tags                       = local.tags`: Passes `tags` (Tags applied to the namespace and the alert): the local value `tags`.
- `queues = {`: Passes `queues` into the module: a group of named values that follows.
- `orders          = {}`: Entry `orders`: `{}`.
- `orders-sessions = { requires_session = true }`: Entry `orders-sessions`: `{ requires_session = true }`.
- Closing lines: `}` end the blocks opened above.

**Lines 119 to 126**

```hcl
module "registry" {
  source = "../../modules/container_registry"

  name                = local.names.registry
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}
```

- `module "registry" {`: Calls a module and names this use of it `registry`; its outputs are read as `module.registry.<output>`.
- `source = "../../modules/container_registry"`: `source` is the folder holding the module's code: the text `"../../modules/container_registry"`.
- `name                = local.names.registry`: Passes `name` (Registry name: 5 to 50 letters and digits, globally unique): the local value `names` field `registry`.
- `resource_group_name = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds the registry): the `name` of the resource `azurerm_resource_group.this`.
- `location            = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `tags                = local.tags`: Passes `tags` (Tags applied to the registry): the local value `tags`.
- Closing line: `}` ends the block opened above.

**Lines 128 to 132**

```hcl
module "role_assignments" {
  source = "../../modules/role_assignments"

  assignments = merge(local.worker_assignments, local.pull_assignments, local.operator_assignments)
}
```

- `module "role_assignments" {`: Calls a module and names this use of it `role_assignments`; its outputs are read as `module.role_assignments.<output>`.
- `source = "../../modules/role_assignments"`: `source` is the folder holding the module's code: the text `"../../modules/role_assignments"`.
- `assignments = merge(local.worker_assignments, local.pull_assignments, local.operator_assignments)`: Passes `assignments` into the module: the local value `worker_assignments`, the local value `pull_assignments`, the local value `operator_assignments`.
- Closing line: `}` ends the block opened above.

**Line 134**

```hcl
module "worker_app" {
```

- `module "worker_app" {`: Calls a module and names this use of it `worker_app`; its outputs are read as `module.worker_app.<output>`.

**Lines 135 to 164**

```hcl
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
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

**New idea.** A **hash** (or *digest*) is a fixed-length fingerprint calculated from some data. The same data always gives the same hash and any change gives a different one, so comparing hashes shows whether a file or an image is exactly the one that was reviewed.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

- `source = "../../modules/worker_app"`: `source` is the folder holding the module's code: the text `"../../modules/worker_app"`.
- `count  = var.deploy_worker ? 1 : 0`: `count`: How many copies to create. Here the input variable `deploy_worker` (False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)).
- `name                       = local.names.worker`: Passes `name` (Container app name, for example ca-orders-worker): the local value `names` field `worker`.
- `environment_name           = local.names.environment`: Passes `environment_name` (Container Apps environment name): the local value `names` field `environment`.
- `resource_group_name        = azurerm_resource_group.this.name`: Passes `resource_group_name` (Resource group that holds both): the `name` of the resource `azurerm_resource_group.this`.
- `location                   = azurerm_resource_group.this.location`: Passes `location` (Azure region): the `location` of the resource `azurerm_resource_group.this`.
- `log_analytics_workspace_id = module.log_analytics.id`: Passes `log_analytics_workspace_id` (Workspace that receives the console logs): the output `id` of the module `log_analytics`.
- `image                      = coalesce(var.image, "unused.azurecr.io/unused:0")`: Passes `image` (Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest): the input variable `image` (Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true).
- `worker_identity_id         = module.worker_identity.id`: Passes `worker_identity_id` (Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)): the output `id` of the module `worker_identity`.
- `pull_identity_id           = module.pull_identity.id`: Passes `pull_identity_id` (Resource id of the identity that only pulls the image (AcrPull on the registry)): the output `id` of the module `pull_identity`.
- `registry_server            = module.registry.login_server`: Passes `registry_server` (Registry host, for example myregistry.azurecr.io): the output `login_server` of the module `registry`.
- `tags                       = local.tags`: Passes `tags` (Tags applied to both resources): the local value `tags`.
- `# Addresses, names and tuning knobs. Nothing here is a secret, and there is no connection string to put here.`: Comment for the reader: Addresses, names and tuning knobs. Nothing here is a secret, and there is no connection string to put here.
- `env = {`: Passes `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value): a group of named values that follows.
- `AZURE_CLIENT_ID      = module.worker_identity.client_id`: Entry `AZURE_CLIENT_ID`: the output `client_id` of the module `worker_identity`.
- `SB_NAMESPACE         = module.servicebus.fully_qualified_namespace`: Entry `SB_NAMESPACE`: the output `fully_qualified_namespace` of the module `servicebus`.
- `SB_QUEUE             = var.worker_queue`: Entry `SB_QUEUE`: the input variable `worker_queue` (The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true).
- `USE_SESSIONS         = var.worker_use_sessions ? "1" : "0"`: Entry `USE_SESSIONS`: the input variable `worker_use_sessions` (Whether the deployed worker uses session receivers (for orders-sessions)).
- `MODE                 = var.worker_mode`: Entry `MODE`: the input variable `worker_mode` (naive or idempotent (lesson step 3)).
- `LOCK_RENEWAL_SECONDS = tostring(var.worker_lock_renewal_seconds)`: Entry `LOCK_RENEWAL_SECONDS`: the input variable `worker_lock_renewal_seconds` (Automatic lock renewal in seconds; 0 turns it off (lesson step 2)). `tostring(x)` converts a value to text.
- `SLOW_EVERY           = tostring(var.worker_slow_every)`: Entry `SLOW_EVERY`: the input variable `worker_slow_every` (Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off).
- `HEALTH_PORT          = "8080"`: Entry `HEALTH_PORT`: the text `"8080"`.
- `LEDGER_PATH          = "/data/orders.db"`: Entry `LEDGER_PATH`: the text `"/data/orders.db"`.
- `SQL_DIR              = "/app/sql"`: Entry `SQL_DIR`: the text `"/app/sql"`.
- `LOG_LEVEL            = "INFO"`: Entry `LOG_LEVEL`: the text `"INFO"`.
- `# The identity must hold its role before the worker starts, or its first receive is a denial.`: Comment for the reader: The identity must hold its role before the worker starts, or its first receive is a denial.
- Closing line: `}` ends the block opened above.

**Lines 165 to 166**

```hcl
  depends_on = [module.role_assignments]
}
```

- `depends_on = [module.role_assignments]`: `depends_on`: Things that must exist first even though nothing is referenced from them. Here the module `role_assignments`.
- Closing line: `}` ends the block opened above.

**Lines 168 to 177**

```hcl
module "budget" {
  source = "../../modules/budget"
  count  = length(var.budget_contact_emails) > 0 ? 1 : 0

  name            = local.names.budget
  subscription_id = var.subscription_id
  amount          = var.budget_amount
  start_date      = coalesce(var.budget_start_date, "2026-01-01T00:00:00Z")
  contact_emails  = var.budget_contact_emails
}
```

**New idea.** A **GUID** (or UUID) is a 128-bit identifier written as 32 hexadecimal digits in groups, such as `00000000-0000-0000-0000-000000000000`. Azure uses them for subscriptions, tenants and identities. The all-zero value in examples is a placeholder, not a real id.

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

- `module "budget" {`: Calls a module and names this use of it `budget`; its outputs are read as `module.budget.<output>`.
- `source = "../../modules/budget"`: `source` is the folder holding the module's code: the text `"../../modules/budget"`.
- `count  = length(var.budget_contact_emails) > 0 ? 1 : 0`: `count`: How many copies to create. Here the input variable `budget_contact_emails` (Recipients of the budget alerts. An empty list creates no budget). `length(x)` counts the items of a list, map or characters of text.
- `name            = local.names.budget`: Passes `name` (Budget name): the local value `names` field `budget`.
- `subscription_id = var.subscription_id`: Passes `subscription_id` (Subscription GUID the budget watches): the input variable `subscription_id` (Subscription GUID (`az account show --query id`)).
- `amount          = var.budget_amount`: Passes `amount` (Monthly amount in the billing currency): the input variable `budget_amount` (Monthly budget in the billing currency).
- `start_date      = coalesce(var.budget_start_date, "2026-01-01T00:00:00Z")`: Passes `start_date` (First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month): the input variable `budget_start_date` (First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contact_emails is set).
- `contact_emails  = var.budget_contact_emails`: Passes `contact_emails` (Addresses that receive the alerts): the input variable `budget_contact_emails` (Recipients of the budget alerts. An empty list creates no budget).
- Closing line: `}` ends the block opened above.

#### `infra/environments/dev/outputs.tf`

60 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "resource_group_name" {
  description = "The one resource group; destroying the environment removes it."
  value       = azurerm_resource_group.this.name
}
```

- `output "resource_group_name" {`: An `output` block exposes a value so that whoever uses this folder (another module, or a person running `terraform output`) can read it. Declares the output `resource_group_name`.
- `description = "The one resource group; destroying the environment removes it."`: `description` documents it: "The one resource group; destroying the environment removes it."
- `value       = azurerm_resource_group.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_resource_group.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "namespace_name" {
  description = "Service Bus namespace name."
  value       = module.servicebus.name
}
```

- `output "namespace_name" {`: Declares the output `namespace_name`.
- `description = "Service Bus namespace name."`: `description` documents it: "Service Bus namespace name."
- `value       = module.servicebus.name`: `value` is what is exposed: the output `name` of the module `servicebus`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
output "servicebus_namespace" {
  description = "The programs' SB_NAMESPACE (fully qualified host name)."
  value       = module.servicebus.fully_qualified_namespace
}
```

- `output "servicebus_namespace" {`: Declares the output `servicebus_namespace`.
- `description = "The programs' SB_NAMESPACE (fully qualified host name)."`: `description` documents it: "The programs' SB_NAMESPACE (fully qualified host name)."
- `value       = module.servicebus.fully_qualified_namespace`: `value` is what is exposed: the output `fully_qualified_namespace` of the module `servicebus`.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
output "queue_names" {
  description = "The queues: orders and orders-sessions."
  value       = module.servicebus.queue_names
}
```

- `output "queue_names" {`: Declares the output `queue_names`.
- `description = "The queues: orders and orders-sessions."`: `description` documents it: "The queues: orders and orders-sessions."
- `value       = module.servicebus.queue_names`: `value` is what is exposed: the output `queue_names` of the module `servicebus`.
- Closing line: `}` ends the block opened above.

**Lines 21 to 24**

```hcl
output "registry_name" {
  description = "Registry name for `az acr build`."
  value       = module.registry.name
}
```

- `output "registry_name" {`: Declares the output `registry_name`.
- `description = "Registry name for `az acr build`."`: `description` documents it: "Registry name for `az acr build`."
- `value       = module.registry.name`: `value` is what is exposed: the output `name` of the module `registry`.
- Closing line: `}` ends the block opened above.

**Lines 26 to 29**

```hcl
output "registry_login_server" {
  description = "Registry host, the prefix of the image name."
  value       = module.registry.login_server
}
```

- `output "registry_login_server" {`: Declares the output `registry_login_server`.
- `description = "Registry host, the prefix of the image name."`: `description` documents it: "Registry host, the prefix of the image name."
- `value       = module.registry.login_server`: `value` is what is exposed: the output `login_server` of the module `registry`.
- Closing line: `}` ends the block opened above.

**Lines 31 to 34**

```hcl
output "worker_identity_name" {
  description = "Name of the identity the worker runs as."
  value       = module.worker_identity.name
}
```

- `output "worker_identity_name" {`: Declares the output `worker_identity_name`.
- `description = "Name of the identity the worker runs as."`: `description` documents it: "Name of the identity the worker runs as."
- `value       = module.worker_identity.name`: `value` is what is exposed: the output `name` of the module `worker_identity`.
- Closing line: `}` ends the block opened above.

**Lines 36 to 39**

```hcl
output "worker_identity_client_id" {
  description = "The worker's AZURE_CLIENT_ID. It names the identity and is not a secret."
  value       = module.worker_identity.client_id
}
```

- `output "worker_identity_client_id" {`: Declares the output `worker_identity_client_id`.
- `description = "The worker's AZURE_CLIENT_ID. It names the identity and is not a secret."`: `description` documents it: "The worker's AZURE_CLIENT_ID. It names the identity and is not a secret."
- `value       = module.worker_identity.client_id`: `value` is what is exposed: the output `client_id` of the module `worker_identity`.
- Closing line: `}` ends the block opened above.

**Lines 41 to 44**

```hcl
output "worker_identity_principal_id" {
  description = "Object id of the worker identity; denial messages in the logs show this value."
  value       = module.worker_identity.principal_id
}
```

- `output "worker_identity_principal_id" {`: Declares the output `worker_identity_principal_id`.
- `description = "Object id of the worker identity; denial messages in the logs show this value."`: `description` documents it: "Object id of the worker identity; denial messages in the logs show this value."
- `value       = module.worker_identity.principal_id`: `value` is what is exposed: the output `principal_id` of the module `worker_identity`.
- Closing line: `}` ends the block opened above.

**Lines 46 to 49**

```hcl
output "log_analytics_customer_id" {
  description = "Workspace customer id for `az monitor log-analytics query --workspace`."
  value       = module.log_analytics.workspace_id
}
```

- `output "log_analytics_customer_id" {`: Declares the output `log_analytics_customer_id`.
- `description = "Workspace customer id for `az monitor log-analytics query --workspace`."`: `description` documents it: "Workspace customer id for `az monitor log-analytics query --workspace`."
- `value       = module.log_analytics.workspace_id`: `value` is what is exposed: the output `workspace_id` of the module `log_analytics`.
- Closing line: `}` ends the block opened above.

**Lines 51 to 54**

```hcl
output "worker_app_name" {
  description = "Container app name, or null until deploy_worker is true."
  value       = one(module.worker_app[*].name)
}
```

- `output "worker_app_name" {`: Declares the output `worker_app_name`.
- `description = "Container app name, or null until deploy_worker is true."`: `description` documents it: "Container app name, or null until deploy_worker is true."
- `value       = one(module.worker_app[*].name)`: `value` is what is exposed: the module `worker_app`. `one(list)` returns the single item of a list of zero or one items (or `null` when empty).
- Closing line: `}` ends the block opened above.

**Lines 56 to 63**

```hcl
output "worker_role_assignments" {
  description = "The worker identity's role assignments: Data Receiver, one per queue, nothing else."
  value = [
    for assignment in module.role_assignments.assignments :
    { role = assignment.role, scope = assignment.scope }
    if assignment.principal_id == module.worker_identity.principal_id
  ]
}
```

- `output "worker_role_assignments" {`: Declares the output `worker_role_assignments`.
- `description = "The worker identity's role assignments: Data Receiver, one per queue, nothing else."`: `description` documents it: "The worker identity's role assignments: Data Receiver, one per queue, nothing else."
- `value = [`: `value` is what is exposed: a list that follows.
- `for assignment in module.role_assignments.assignments :`: Part of a `for` expression: `for assignment in module.role_assignments.assignments :`.
- `{ role = assignment.role, scope = assignment.scope }`: Item: `{ role = assignment.role, scope = assignment.scope }`.
- `if assignment.principal_id == module.worker_identity.principal_id`: Part of a `for` expression: `if assignment.principal_id == module.worker_identity.principal_id`.
- Closing lines: `]`, `}` end the blocks opened above.

**Lines 65 to 72**

```hcl
output "operator_role_assignments" {
  description = "The operator's role assignments (empty when operator_object_id is null)."
  value = [
    for key, assignment in module.role_assignments.assignments :
    { key = key, role = assignment.role, scope = assignment.scope }
    if startswith(key, "operator_")
  ]
}
```

- `output "operator_role_assignments" {`: Declares the output `operator_role_assignments`.
- `description = "The operator's role assignments (empty when operator_object_id is null)."`: `description` documents it: "The operator's role assignments (empty when operator_object_id is null)."
- `value = [`: `value` is what is exposed: a list that follows.
- `for key, assignment in module.role_assignments.assignments :`: Part of a `for` expression: `for key, assignment in module.role_assignments.assignments :`.
- `{ key = key, role = assignment.role, scope = assignment.scope }`: Item: `{ key = key, role = assignment.role, scope = assignment.scope }`.
- `if startswith(key, "operator_")`: Part of a `for` expression: `if startswith(key, "operator_")`. `startswith(text, prefix)` is true when the text starts with the prefix.
- Closing lines: `]`, `}` end the blocks opened above.

#### `infra/environments/dev/terraform.tfvars.example`

23 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 2**

```text
# Copy to terraform.tfvars (git-ignored) or let scripts/provision.sh write it from `az account show`.
# None of these values is a secret; the subscription and tenant ids are still personal, so the real file stays out of git.
```

**New idea.** **git** is the version-control system that records every change to the project's files as a numbered commit, so any earlier state can be recovered and changes can be reviewed. Files listed in `.gitignore` are never recorded.

- `# Copy to terraform.tfvars (git-ignored) or let scripts/provision.sh write it from `az account show`.`: Comment for the reader: Copy to terraform.tfvars (git-ignored) or let scripts/provision.sh write it from `az account show`.
- `# None of these values is a secret; the subscription and tenant ids are still personal, so the real file stays`…: Comment for the reader: None of these values is a secret; the subscription and tenant ids are still personal, so the real file stays out of git.

**Lines 4 to 5**

```text
subscription_id = "00000000-0000-0000-0000-000000000000"
tenant_id       = "00000000-0000-0000-0000-000000000000"
```

- `subscription_id = "00000000-0000-0000-0000-000000000000"`: A `.tfvars` file assigns values to input variables (`name = value`), one per line. Terraform reads `terraform.tfvars` automatically; other files are passed with `-var-file=`. Sets the input variable `subscription_id` (Subscription GUID (`az account show --query id`)) to the text `"00000000-0000-0000-0000-000000000000"`.
- `tenant_id       = "00000000-0000-0000-0000-000000000000"`: Sets the input variable `tenant_id` (Entra tenant GUID (`az account show --query tenantId`)) to the text `"00000000-0000-0000-0000-000000000000"`.

**Lines 7 to 8**

```text
location    = "westeurope"
name_prefix = "orders"
```

- `location    = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- `name_prefix = "orders"`: Sets the input variable `name_prefix` (Short lowercase word in every resource name. Letters and digits only) to the text `"orders"`.

**Lines 10 to 11**

```text
# az ad signed-in-user show --query id --output tsv
operator_object_id = null
```

- `# az ad signed-in-user show --query id --output tsv`: Comment for the reader: az ad signed-in-user show --query id --output tsv
- `operator_object_id = null`: Sets the input variable `operator_object_id` (Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing) to `null` (not set).

**Lines 13 to 14**

```text
# Mails when any dead-letter queue is not empty.
alert_email_addresses = ["you@example.com"]
```

- `# Mails when any dead-letter queue is not empty.`: Comment for the reader: Mails when any dead-letter queue is not empty.
- `alert_email_addresses = ["you@example.com"]`: Sets the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert) to `["you@example.com"]`.

**Lines 16 to 17**

```text
# A safety net: a Standard namespace bills by the hour.
budget_contact_emails = ["you@example.com"]
```

- `# A safety net: a Standard namespace bills by the hour.`: Comment for the reader: A safety net: a Standard namespace bills by the hour.
- `budget_contact_emails = ["you@example.com"]`: Sets the input variable `budget_contact_emails` (Recipients of the budget alerts. An empty list creates no budget) to `["you@example.com"]`.

**Lines 18 to 19**

```text
budget_amount         = 30
budget_start_date     = "2026-11-01T00:00:00Z"
```

- `budget_amount         = 30`: Sets the input variable `budget_amount` (Monthly budget in the billing currency) to the number `30`.
- `budget_start_date     = "2026-11-01T00:00:00Z"`: Sets the input variable `budget_start_date` (First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contact_emails is set) to the text `"2026-11-01T00:00:00Z"`.

**Lines 21 to 22**

```text
# Phase 1 leaves these off. Phase 2 (scripts/build-and-deploy.sh) sets them.
deploy_worker = false
```

- `# Phase 1 leaves these off. Phase 2 (scripts/build-and-deploy.sh) sets them.`: Comment for the reader: Phase 1 leaves these off. Phase 2 (scripts/build-and-deploy.sh) sets them.
- `deploy_worker = false`: Sets the input variable `deploy_worker` (False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)) to `false`.

**Line 23**

```text
image         = null
```

- `image         = null`: Sets the input variable `image` (Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true) to `null` (not set).

**Lines 25 to 26**

```text
# What the deployed worker does (lesson steps 2 and 3).
worker_queue                = "orders"
```

- `# What the deployed worker does (lesson steps 2 and 3).`: Comment for the reader: What the deployed worker does (lesson steps 2 and 3).
- `worker_queue                = "orders"`: Sets the input variable `worker_queue` (The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true) to the text `"orders"`.

**Lines 27 to 30**

```text
worker_use_sessions         = false
worker_mode                 = "idempotent"
worker_lock_renewal_seconds = 300
worker_slow_every           = 0
```

- `worker_use_sessions         = false`: Sets the input variable `worker_use_sessions` (Whether the deployed worker uses session receivers (for orders-sessions)) to `false`.
- `worker_mode                 = "idempotent"`: Sets the input variable `worker_mode` (naive or idempotent (lesson step 3)) to the text `"idempotent"`.
- `worker_lock_renewal_seconds = 300`: Sets the input variable `worker_lock_renewal_seconds` (Automatic lock renewal in seconds; 0 turns it off (lesson step 2)) to the number `300`.
- `worker_slow_every           = 0`: Sets the input variable `worker_slow_every` (Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off) to the number `0`.

#### `infra/environments/dev/tests/dev.tftest.hcl`

163 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 2**

```hcl
# Plans and applies the whole environment against a mocked azurerm provider: no credentials, no network.
# It proves the composition (who holds which role on which queue, what the worker is told) and the guards, not Azure's behavior.
```

- `# Plans and applies the whole environment against a mocked azurerm provider: no credentials, no network.`: Comment for the reader: Plans and applies the whole environment against a mocked azurerm provider: no credentials, no network.
- `# It proves the composition (who holds which role on which queue, what the worker is told) and the guards, not`…: Comment for the reader: It proves the composition (who holds which role on which queue, what the worker is told) and the guards, not Azure's behavior.

**Lines 4 to 31**

```hcl
mock_provider "azurerm" {
  mock_resource "azurerm_servicebus_namespace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"
    }
  }
  mock_resource "azurerm_servicebus_queue" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/mock"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ContainerRegistry/registries/acrordersabcde"
      login_server = "acrordersabcde.azurecr.io"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.OperationalInsights/workspaces/law-orders"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.App/managedEnvironments/cae-orders"
    }
  }
}
```

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

- `mock_provider "azurerm" {`: `mock_provider "azurerm" { ... }` replaces the real `azurerm` provider with a fake for this test file. Instead of calling Azure, the fake invents a value for every setting Terraform asks for. That is how the tests plan and apply the configuration with no Azure account and no network. Starts a `mock_provider` block for `azurerm`.
- `mock_resource "azurerm_servicebus_namespace" {`: `mock_resource "type" { defaults = { ... } }` sets the values the fake provider returns for that resource type (here: ids shaped like real Azure ids, so checks that read an id can run). Starts a `mock_resource` block for `azurerm_servicebus_namespace`.
- `defaults = {`: `defaults = { ... }` lists the fake values returned for that resource type. The fake values follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.Service`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"`.
- `mock_resource "azurerm_servicebus_queue" {`: Starts a `mock_resource` block for `azurerm_servicebus_queue`.
- `defaults = {`: The fake values follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.Service`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/mock"`.
- `mock_resource "azurerm_container_registry" {`: Starts a `mock_resource` block for `azurerm_container_registry`.
- `defaults = {`: The fake values follow.
- `id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microso`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ContainerRegistry/registries/acrordersabcde"`.
- `login_server = "acrordersabcde.azurecr.io"`: Entry `login_server`: the text `"acrordersabcde.azurecr.io"`.
- `mock_resource "azurerm_log_analytics_workspace" {`: Starts a `mock_resource` block for `azurerm_log_analytics_workspace`.
- `defaults = {`: The fake values follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.Operati`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.OperationalInsights/workspaces/law-orders"`.
- `mock_resource "azurerm_container_app_environment" {`: Starts a `mock_resource` block for `azurerm_container_app_environment`.
- `defaults = {`: The fake values follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.App/man`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.App/managedEnvironments/cae-orders"`.
- Closing lines: `}` end the blocks opened above.

**Lines 33 to 38**

```hcl
override_resource {
  target = module.servicebus.azurerm_servicebus_queue.this["orders"]
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"
  }
}
```

- `override_resource {`: `override_resource { target = ...  values = { ... } }` fixes the settings of one specific resource instance (named by its address) instead of letting the mock invent them; the tests use it to give an identity a known principal id so that assertions can compare it. Starts an `override_resource` block.
- `target = module.servicebus.azurerm_servicebus_queue.this["orders"]`: `target` names the resource instance by address, such as `azurerm_user_assigned_identity.this`. `target` is the output `azurerm_servicebus_queue` of the module `servicebus`.
- `values = {`: `values = { ... }` lists the settings to force. The settings follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.Service`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"`.
- Closing lines: `}` end the blocks opened above.

**Lines 40 to 45**

```hcl
override_resource {
  target = module.servicebus.azurerm_servicebus_queue.this["orders-sessions"]
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions"
  }
}
```

- `override_resource {`: Starts an `override_resource` block.
- `target = module.servicebus.azurerm_servicebus_queue.this["orders-sessions"]`: `target` is the output `azurerm_servicebus_queue` of the module `servicebus`.
- `values = {`: The settings follow.
- `id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.Service`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions"`.
- Closing lines: `}` end the blocks opened above.

**Lines 47 to 54**

```hcl
override_resource {
  target = module.worker_identity.azurerm_user_assigned_identity.this
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-worker"
    principal_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    client_id    = "cccccccc-cccc-cccc-cccc-cccccccccccc"
  }
}
```

- `override_resource {`: Starts an `override_resource` block.
- `target = module.worker_identity.azurerm_user_assigned_identity.this`: `target` is the output `azurerm_user_assigned_identity` of the module `worker_identity`.
- `values = {`: The settings follow.
- `id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microso`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-worker"`.
- `principal_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`: Entry `principal_id`: the text `"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`.
- `client_id    = "cccccccc-cccc-cccc-cccc-cccccccccccc"`: Entry `client_id`: the text `"cccccccc-cccc-cccc-cccc-cccccccccccc"`.
- Closing lines: `}` end the blocks opened above.

**Lines 56 to 63**

```hcl
override_resource {
  target = module.pull_identity.azurerm_user_assigned_identity.this
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-pull"
    principal_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    client_id    = "dddddddd-dddd-dddd-dddd-dddddddddddd"
  }
}
```

- `override_resource {`: Starts an `override_resource` block.
- `target = module.pull_identity.azurerm_user_assigned_identity.this`: `target` is the output `azurerm_user_assigned_identity` of the module `pull_identity`.
- `values = {`: The settings follow.
- `id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microso`…: Entry `id`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-pull"`.
- `principal_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`: Entry `principal_id`: the text `"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`.
- `client_id    = "dddddddd-dddd-dddd-dddd-dddddddddddd"`: Entry `client_id`: the text `"dddddddd-dddd-dddd-dddd-dddddddddddd"`.
- Closing lines: `}` end the blocks opened above.

**Lines 65 to 69**

```hcl
variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  tenant_id       = "11111111-1111-1111-1111-111111111111"
  suffix          = "abcde"
}
```

- `variables {`: A `variables { ... }` block gives values to the input variables: at the top of the file for every step, or inside a `run` block for that step only. Starts a `variables` block.
- `subscription_id = "00000000-0000-0000-0000-000000000000"`: Sets the input variable `subscription_id` (Subscription GUID (`az account show --query id`)) to the text `"00000000-0000-0000-0000-000000000000"`.
- `tenant_id       = "11111111-1111-1111-1111-111111111111"`: Sets the input variable `tenant_id` (Entra tenant GUID (`az account show --query tenantId`)) to the text `"11111111-1111-1111-1111-111111111111"`.
- `suffix          = "abcde"`: Sets the input variable `suffix` (Characters that make the namespace and registry names globally unique. Leave null to generate five) to the text `"abcde"`.
- Closing line: `}` ends the block opened above.

**Lines 71 to 91**

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
```

- `run "the_worker_holds_only_data_receiver_one_per_queue_and_never_the_owner_role" {`: A `run "name" { ... }` block is one test step. Terraform plans (or plans and applies) the configuration against the mock provider, then evaluates the `assert` blocks. Steps run in file order and a failed `assert` fails the test. Starts the test step `the worker holds only data receiver one per queue and never the owner role`.
- `command = apply`: `command = apply` runs a full apply against the mock, so values computed on creation are available to the assertions. It is the default when `command` is left out. `command = apply`.
- `assert {`: An `assert { condition = ...  error_message = ... }` block states something that must be true. If the condition is false, the step fails and prints the message. Starts an `assert` block.
- `condition     = length(output.worker_role_assignments) == 2`: `condition` is the rule: `length(output.worker_role_assignments) == 2` must be true.
- `error_message = "one Data Receiver assignment per queue and nothing else"`: `error_message` is shown when the rule fails: "one Data Receiver assignment per queue and nothing else"
- `assert {`: Starts an `assert` block.
- `condition     = alltrue([for assignment in output.worker_role_assignments : assignment.role == "Azure Service `…: `condition` is the rule: `alltrue([for assignment in output.worker_role_assignments : assignment.role == "Azure Service Bus Data Receiver"])` must be true. `alltrue(list)` is true when every item is true.
- `error_message = "the worker may only receive"`: `error_message` is shown when the rule fails: "the worker may only receive"
- `assert {`: Starts an `assert` block.
- `condition = toset([for assignment in output.worker_role_assignments : assignment.scope]) == toset([`: `condition` is the rule: `toset([for assignment in output.worker_role_assignments : assignment.scope]) == toset([` must be true. `toset(list)` converts a list to a set (no duplicates, no order).
- `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/n`…: Item: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"`.
- `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/n`…: Item: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions"`.
- `error_message = "each assignment must be scoped to one queue, not the namespace or the group"`: `error_message` is shown when the rule fails: "each assignment must be scoped to one queue, not the namespace or the group"
- Closing lines: `}`, `])` end the blocks opened above.

**Lines 93 to 100**

```hcl
run "the_pull_identity_reads_the_registry_and_nothing_else" {
  command = apply

  assert {
    condition     = length([for assignment in module.role_assignments.assignments : assignment if assignment.principal_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]) == 1
    error_message = "the pull identity holds one role"
  }
}
```

- `run "the_pull_identity_reads_the_registry_and_nothing_else" {`: Starts the test step `the pull identity reads the registry and nothing else`.
- `command = apply`: `command = apply`.
- `assert {`: Starts an `assert` block.
- `condition     = length([for assignment in module.role_assignments.assignments : assignment if assignment.princ`…: `condition` is the rule: `length([for assignment in module.role_assignments.assignments : assignment if assignment.principal_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]) == 1` must be true.
- `error_message = "the pull identity holds one role"`: `error_message` is shown when the rule fails: "the pull identity holds one role"
- Closing lines: `}` end the blocks opened above.

**Lines 102 to 109**

```hcl
run "no_operator_roles_unless_asked" {
  command = apply

  assert {
    condition     = length(output.operator_role_assignments) == 0 && length(module.role_assignments.assignments) == 3
    error_message = "two for the worker, one for the pull identity, none for an operator that was not named"
  }
}
```

- `run "no_operator_roles_unless_asked" {`: Starts the test step `no operator roles unless asked`.
- `command = apply`: `command = apply`.
- `assert {`: Starts an `assert` block.
- `condition     = length(output.operator_role_assignments) == 0 && length(module.role_assignments.assignments) =`…: `condition` is the rule: `length(output.operator_role_assignments) == 0 && length(module.role_assignments.assignments) == 3` must be true.
- `error_message = "two for the worker, one for the pull identity, none for an operator that was not named"`: `error_message` is shown when the rule fails: "two for the worker, one for the pull identity, none for an operator that was not named"
- Closing lines: `}` end the blocks opened above.

**Lines 111 to 127**

```hcl
run "a_named_operator_may_send_and_receive_on_each_queue_but_not_manage_the_namespace" {
  command = apply

  variables {
    operator_object_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
  }

  assert {
    condition     = length(output.operator_role_assignments) == 4
    error_message = "Data Sender and Data Receiver on each of the two queues"
  }

  assert {
    condition     = toset([for assignment in output.operator_role_assignments : assignment.role]) == toset(["Azure Service Bus Data Sender", "Azure Service Bus Data Receiver"])
    error_message = "the operator holds the two data roles and no management role"
  }
}
```

- `run "a_named_operator_may_send_and_receive_on_each_queue_but_not_manage_the_namespace" {`: Starts the test step `a named operator may send and receive on each queue but not manage the namespace`.
- `command = apply`: `command = apply`.
- `variables {`: Starts a `variables` block.
- `operator_object_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"`: Sets the input variable `operator_object_id` (Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing) to the text `"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"`.
- `assert {`: Starts an `assert` block.
- `condition     = length(output.operator_role_assignments) == 4`: `condition` is the rule: `length(output.operator_role_assignments) == 4` must be true.
- `error_message = "Data Sender and Data Receiver on each of the two queues"`: `error_message` is shown when the rule fails: "Data Sender and Data Receiver on each of the two queues"
- `assert {`: Starts an `assert` block.
- `condition     = toset([for assignment in output.operator_role_assignments : assignment.role]) == toset(["Azure`…: `condition` is the rule: `toset([for assignment in output.operator_role_assignments : assignment.role]) == toset(["Azure Service Bus Data Sender", "Azure Service Bus Data Receiver"])` must be true.
- `error_message = "the operator holds the two data roles and no management role"`: `error_message` is shown when the rule fails: "the operator holds the two data roles and no management role"
- Closing lines: `}` end the blocks opened above.

**Lines 129 to 141**

```hcl
run "the_first_phase_builds_everything_except_the_worker" {
  command = apply

  assert {
    condition     = output.worker_app_name == null
    error_message = "with deploy_worker false there is no container app"
  }

  assert {
    condition     = output.servicebus_namespace == "sb-orders-abcde.servicebus.windows.net" && toset(output.queue_names) == toset(["orders", "orders-sessions"])
    error_message = "the namespace host and both queues must be exposed to the programs"
  }
}
```

- `run "the_first_phase_builds_everything_except_the_worker" {`: Starts the test step `the first phase builds everything except the worker`.
- `command = apply`: `command = apply`.
- `assert {`: Starts an `assert` block.
- `condition     = output.worker_app_name == null`: `condition` is the rule: `output.worker_app_name == null` must be true.
- `error_message = "with deploy_worker false there is no container app"`: `error_message` is shown when the rule fails: "with deploy_worker false there is no container app"
- `assert {`: Starts an `assert` block.
- `condition     = output.servicebus_namespace == "sb-orders-abcde.servicebus.windows.net" && toset(output.queue_`…: `condition` is the rule: `output.servicebus_namespace == "sb-orders-abcde.servicebus.windows.net" && toset(output.queue_names) == toset(["orders", "orders-sessions"])` must be true.
- `error_message = "the namespace host and both queues must be exposed to the programs"`: `error_message` is shown when the rule fails: "the namespace host and both queues must be exposed to the programs"
- Closing lines: `}` end the blocks opened above.

**Lines 143 to 155**

```hcl
run "the_second_phase_adds_the_worker" {
  command = apply

  variables {
    deploy_worker = true
    image         = "acrordersabcde.azurecr.io/azure-service-bus-worker:0.1.0"
  }

  assert {
    condition     = output.worker_app_name == "ca-orders-worker"
    error_message = "the worker must be created in phase two"
  }
}
```

- `run "the_second_phase_adds_the_worker" {`: Starts the test step `the second phase adds the worker`.
- `command = apply`: `command = apply`.
- `variables {`: Starts a `variables` block.
- `deploy_worker = true`: Sets the input variable `deploy_worker` (False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)) to `true`.
- `image         = "acrordersabcde.azurecr.io/azure-service-bus-worker:0.1.0"`: Sets the input variable `image` (Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true) to the text `"acrordersabcde.azurecr.io/azure-service-bus-worker:0.1.0"`.
- `assert {`: Starts an `assert` block.
- `condition     = output.worker_app_name == "ca-orders-worker"`: `condition` is the rule: `output.worker_app_name == "ca-orders-worker"` must be true.
- `error_message = "the worker must be created in phase two"`: `error_message` is shown when the rule fails: "the worker must be created in phase two"
- Closing lines: `}` end the blocks opened above.

**Lines 157 to 165**

```hcl
run "a_worker_without_an_image_is_refused" {
  command = plan

  variables {
    deploy_worker = true
  }

  expect_failures = [var.image]
}
```

- `run "a_worker_without_an_image_is_refused" {`: Starts the test step `a worker without an image is refused`.
- `command = plan`: `command = plan` only computes what would be created. Values that exist only after creation (ids) are unknown, so this suits checks on inputs and fixed settings. `command = plan`.
- `variables {`: Starts a `variables` block.
- `deploy_worker = true`: Sets the input variable `deploy_worker` (False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)) to `true`.
- `expect_failures = [var.image]`: `expect_failures = [var.x]` says this step is *meant* to fail on that variable's validation (or a precondition). The step passes only if that failure happens, which is how rules that refuse bad input are tested. Expects the failure of [var.image].
- Closing lines: `}` end the blocks opened above.

**Lines 167 to 175**

```hcl
run "an_unknown_worker_queue_is_refused" {
  command = plan

  variables {
    worker_queue = "payments"
  }

  expect_failures = [var.worker_queue]
}
```

- `run "an_unknown_worker_queue_is_refused" {`: Starts the test step `an unknown worker queue is refused`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `worker_queue = "payments"`: Sets the input variable `worker_queue` (The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true) to the text `"payments"`.
- `expect_failures = [var.worker_queue]`: Expects the failure of [var.worker_queue].
- Closing lines: `}` end the blocks opened above.

**Lines 177 to 185**

```hcl
run "a_budget_needs_a_start_date" {
  command = plan

  variables {
    budget_contact_emails = ["owner@example.com"]
  }

  expect_failures = [var.budget_start_date]
}
```

- `run "a_budget_needs_a_start_date" {`: Starts the test step `a budget needs a start date`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `budget_contact_emails = ["owner@example.com"]`: Sets the input variable `budget_contact_emails` (Recipients of the budget alerts. An empty list creates no budget) to `["owner@example.com"]`.
- `expect_failures = [var.budget_start_date]`: Expects the failure of [var.budget_start_date].
- Closing lines: `}` end the blocks opened above.

**Lines 187 to 199**

```hcl
run "names_are_built_from_the_prefix_and_suffix_and_tagged" {
  command = plan

  assert {
    condition     = azurerm_resource_group.this.name == "rg-orders" && module.servicebus.name == "sb-orders-abcde" && module.registry.name == "acrordersabcde"
    error_message = "names must follow rg-orders, sb-orders-<suffix>, acrorders<suffix>"
  }

  assert {
    condition     = azurerm_resource_group.this.tags["managed_by"] == "terraform" && azurerm_resource_group.this.tags["project"] == "azure-service-bus-worker"
    error_message = "the standard tags must be present"
  }
}
```

- `run "names_are_built_from_the_prefix_and_suffix_and_tagged" {`: Starts the test step `names are built from the prefix and suffix and tagged`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_resource_group.this.name == "rg-orders" && module.servicebus.name == "sb-orders-abcde"`…: `condition` is the rule: `azurerm_resource_group.this.name == "rg-orders" && module.servicebus.name == "sb-orders-abcde" && module.registry.name == "acrordersabcde"` must be true.
- `error_message = "names must follow rg-orders, sb-orders-<suffix>, acrorders<suffix>"`: `error_message` is shown when the rule fails: "names must follow rg-orders, sb-orders-<suffix>, acrorders<suffix>"
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_resource_group.this.tags["managed_by"] == "terraform" && azurerm_resource_group.this.t`…: `condition` is the rule: `azurerm_resource_group.this.tags["managed_by"] == "terraform" && azurerm_resource_group.this.tags["project"] == "azure-service-bus-worker"` must be true.
- `error_message = "the standard tags must be present"`: `error_message` is shown when the rule fails: "the standard tags must be present"
- Closing lines: `}` end the blocks opened above.

#### `infra/environments/dev/variables.tf`

125 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 9**

```hcl
variable "subscription_id" {
  description = "Subscription GUID (`az account show --query id`)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}
```

**New idea.** A **regular expression** is a compact pattern for matching text: `[a-z]` is one lowercase letter, `+` means one or more, `^` and `$` mark the start and end, `{1,127}` means one to 127 repeats.

- `variable "subscription_id" {`: A `variable` block declares an **input**: a value the caller supplies when using this configuration or module. Inside the folder it is read as `var.<name>`. Terraform checks the value against `type` and any `validation` rules before doing anything. Declares the input variable `subscription_id`.
- `description = "Subscription GUID (`az account show --query id`)."`: `description` documents it: "Subscription GUID (`az account show --query id`)."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: A `validation` block makes Terraform refuse a bad input value early. The `condition` is an expression that must be true; if it is false Terraform stops and prints `error_message`. Starts a rule the input value must satisfy.
- `condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))`: `condition` is the rule: `can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))` must be true. `can(expr)` is true when the expression evaluates without an error. `regex(pattern, text)` returns the part of the text that matches a regular expression, and fails if there is no match.
- `error_message = "subscription_id must be a GUID."`: `error_message` is shown when the rule fails: "subscription_id must be a GUID."
- Closing lines: `}` end the blocks opened above.

**Lines 11 to 19**

```hcl
variable "tenant_id" {
  description = "Entra tenant GUID (`az account show --query tenantId`)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}
```

- `variable "tenant_id" {`: Declares the input variable `tenant_id`.
- `description = "Entra tenant GUID (`az account show --query tenantId`)."`: `description` documents it: "Entra tenant GUID (`az account show --query tenantId`)."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))`: `condition` is the rule: `can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))` must be true.
- `error_message = "tenant_id must be a GUID."`: `error_message` is shown when the rule fails: "tenant_id must be a GUID."
- Closing lines: `}` end the blocks opened above.

**Lines 21 to 25**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
  default     = "westeurope"
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "westeurope"`: `default` is used when the caller passes nothing: the text `"westeurope"`.
- Closing line: `}` ends the block opened above.

**Lines 27 to 31**

```hcl
variable "environment" {
  description = "Environment name, used in tags."
  type        = string
  default     = "dev"
}
```

- `variable "environment" {`: Declares the input variable `environment`.
- `description = "Environment name, used in tags."`: `description` documents it: "Environment name, used in tags."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "dev"`: `default` is used when the caller passes nothing: the text `"dev"`.
- Closing line: `}` ends the block opened above.

**Lines 33 to 42**

```hcl
variable "name_prefix" {
  description = "Short lowercase word in every resource name. Letters and digits only."
  type        = string
  default     = "orders"

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.name_prefix))
    error_message = "name_prefix must be 3 to 12 lowercase letters or digits."
  }
}
```

- `variable "name_prefix" {`: Declares the input variable `name_prefix`.
- `description = "Short lowercase word in every resource name. Letters and digits only."`: `description` documents it: "Short lowercase word in every resource name. Letters and digits only."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "orders"`: `default` is used when the caller passes nothing: the text `"orders"`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[a-z0-9]{3,12}$", var.name_prefix))`: `condition` is the rule: `can(regex("^[a-z0-9]{3,12}$", var.name_prefix))` must be true.
- `error_message = "name_prefix must be 3 to 12 lowercase letters or digits."`: `error_message` is shown when the rule fails: "name_prefix must be 3 to 12 lowercase letters or digits."
- Closing lines: `}` end the blocks opened above.

**Lines 44 to 53**

```hcl
variable "suffix" {
  description = "Characters that make the namespace and registry names globally unique. Leave null to generate five."
  type        = string
  default     = null

  validation {
    condition     = var.suffix == null || can(regex("^[a-z0-9]{3,6}$", var.suffix))
    error_message = "suffix must be 3 to 6 lowercase letters or digits."
  }
}
```

- `variable "suffix" {`: Declares the input variable `suffix`.
- `description = "Characters that make the namespace and registry names globally unique. Leave null to generate f`…: `description` documents it: "Characters that make the namespace and registry names globally unique. Leave null to generate five."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = null`: `default` is used when the caller passes nothing: `null` (not set).
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = var.suffix == null || can(regex("^[a-z0-9]{3,6}$", var.suffix))`: `condition` is the rule: `var.suffix == null || can(regex("^[a-z0-9]{3,6}$", var.suffix))` must be true.
- `error_message = "suffix must be 3 to 6 lowercase letters or digits."`: `error_message` is shown when the rule fails: "suffix must be 3 to 6 lowercase letters or digits."
- Closing lines: `}` end the blocks opened above.

**Lines 55 to 59**

```hcl
variable "operator_object_id" {
  description = "Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing."
  type        = string
  default     = null
}
```

- `variable "operator_object_id" {`: Declares the input variable `operator_object_id`.
- `description = "Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get `…: `description` documents it: "Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = null`: `default` is used when the caller passes nothing: `null` (not set).
- Closing line: `}` ends the block opened above.

**Lines 61 to 65**

```hcl
variable "alert_email_addresses" {
  description = "Recipients of the dead-letter alert. Empty creates no alert."
  type        = list(string)
  default     = []
}
```

- `variable "alert_email_addresses" {`: Declares the input variable `alert_email_addresses`.
- `description = "Recipients of the dead-letter alert. Empty creates no alert."`: `description` documents it: "Recipients of the dead-letter alert. Empty creates no alert."
- `type        = list(string)`: `type` limits what is accepted: `list(string)`: an ordered list of texts.
- `default     = []`: `default` is used when the caller passes nothing: `[]`.
- Closing line: `}` ends the block opened above.

**Lines 67 to 71**

```hcl
variable "deploy_worker" {
  description = "False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)."
  type        = bool
  default     = false
}
```

- `variable "deploy_worker" {`: Declares the input variable `deploy_worker`.
- `description = "False creates everything except the container app, so the image can be built in the registry fi`…: `description` documents it: "False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)."
- `type        = bool`: `type` limits what is accepted: `bool`: `true` or `false`.
- `default     = false`: `default` is used when the caller passes nothing: `false`.
- Closing line: `}` ends the block opened above.

**Lines 73 to 82**

```hcl
variable "image" {
  description = "Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true."
  type        = string
  default     = null

  validation {
    condition     = !var.deploy_worker || var.image != null
    error_message = "Set image when deploy_worker is true."
  }
}
```

- `variable "image" {`: Declares the input variable `image`.
- `description = "Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when d`…: `description` documents it: "Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = null`: `default` is used when the caller passes nothing: `null` (not set).
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = !var.deploy_worker || var.image != null`: `condition` is the rule: `!var.deploy_worker || var.image != null` must be true.
- `error_message = "Set image when deploy_worker is true."`: `error_message` is shown when the rule fails: "Set image when deploy_worker is true."
- Closing lines: `}` end the blocks opened above.

**Lines 84 to 93**

```hcl
variable "worker_queue" {
  description = "The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true."
  type        = string
  default     = "orders"

  validation {
    condition     = contains(["orders", "orders-sessions"], var.worker_queue)
    error_message = "worker_queue must be orders or orders-sessions."
  }
}
```

- `variable "worker_queue" {`: Declares the input variable `worker_queue`.
- `description = "The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true."`: `description` documents it: "The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "orders"`: `default` is used when the caller passes nothing: the text `"orders"`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = contains(["orders", "orders-sessions"], var.worker_queue)`: `condition` is the rule: `contains(["orders", "orders-sessions"], var.worker_queue)` must be true. `contains(list, value)` is true when the list holds the value.
- `error_message = "worker_queue must be orders or orders-sessions."`: `error_message` is shown when the rule fails: "worker_queue must be orders or orders-sessions."
- Closing lines: `}` end the blocks opened above.

**Lines 95 to 99**

```hcl
variable "worker_use_sessions" {
  description = "Whether the deployed worker uses session receivers (for orders-sessions)."
  type        = bool
  default     = false
}
```

- `variable "worker_use_sessions" {`: Declares the input variable `worker_use_sessions`.
- `description = "Whether the deployed worker uses session receivers (for orders-sessions)."`: `description` documents it: "Whether the deployed worker uses session receivers (for orders-sessions)."
- `type        = bool`: `type` limits what is accepted: `bool`: `true` or `false`.
- `default     = false`: `default` is used when the caller passes nothing: `false`.
- Closing line: `}` ends the block opened above.

**Lines 101 to 110**

```hcl
variable "worker_mode" {
  description = "naive or idempotent (lesson step 3)."
  type        = string
  default     = "idempotent"

  validation {
    condition     = contains(["naive", "idempotent"], var.worker_mode)
    error_message = "worker_mode must be naive or idempotent."
  }
}
```

- `variable "worker_mode" {`: Declares the input variable `worker_mode`.
- `description = "naive or idempotent (lesson step 3)."`: `description` documents it: "naive or idempotent (lesson step 3)."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "idempotent"`: `default` is used when the caller passes nothing: the text `"idempotent"`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = contains(["naive", "idempotent"], var.worker_mode)`: `condition` is the rule: `contains(["naive", "idempotent"], var.worker_mode)` must be true.
- `error_message = "worker_mode must be naive or idempotent."`: `error_message` is shown when the rule fails: "worker_mode must be naive or idempotent."
- Closing lines: `}` end the blocks opened above.

**Lines 112 to 116**

```hcl
variable "worker_lock_renewal_seconds" {
  description = "Automatic lock renewal in seconds; 0 turns it off (lesson step 2)."
  type        = number
  default     = 300
}
```

- `variable "worker_lock_renewal_seconds" {`: Declares the input variable `worker_lock_renewal_seconds`.
- `description = "Automatic lock renewal in seconds; 0 turns it off (lesson step 2)."`: `description` documents it: "Automatic lock renewal in seconds; 0 turns it off (lesson step 2)."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 300`: `default` is used when the caller passes nothing: the number `300`.
- Closing line: `}` ends the block opened above.

**Lines 118 to 122**

```hcl
variable "worker_slow_every" {
  description = "Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off."
  type        = number
  default     = 0
}
```

- `variable "worker_slow_every" {`: Declares the input variable `worker_slow_every`.
- `description = "Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off."`: `description` documents it: "Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 0`: `default` is used when the caller passes nothing: the number `0`.
- Closing line: `}` ends the block opened above.

**Lines 124 to 128**

```hcl
variable "budget_contact_emails" {
  description = "Recipients of the budget alerts. An empty list creates no budget."
  type        = list(string)
  default     = []
}
```

- `variable "budget_contact_emails" {`: Declares the input variable `budget_contact_emails`.
- `description = "Recipients of the budget alerts. An empty list creates no budget."`: `description` documents it: "Recipients of the budget alerts. An empty list creates no budget."
- `type        = list(string)`: `type` limits what is accepted: `list(string)`: an ordered list of texts.
- `default     = []`: `default` is used when the caller passes nothing: `[]`.
- Closing line: `}` ends the block opened above.

**Lines 130 to 134**

```hcl
variable "budget_amount" {
  description = "Monthly budget in the billing currency."
  type        = number
  default     = 30
}
```

- `variable "budget_amount" {`: Declares the input variable `budget_amount`.
- `description = "Monthly budget in the billing currency."`: `description` documents it: "Monthly budget in the billing currency."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 30`: `default` is used when the caller passes nothing: the number `30`.
- Closing line: `}` ends the block opened above.

**Lines 136 to 145**

```hcl
variable "budget_start_date" {
  description = "First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contact_emails is set."
  type        = string
  default     = null

  validation {
    condition     = length(var.budget_contact_emails) == 0 || var.budget_start_date != null
    error_message = "Set budget_start_date when budget_contact_emails is set."
  }
}
```

- `variable "budget_start_date" {`: Declares the input variable `budget_start_date`.
- `description = "First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contac`…: `description` documents it: "First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contact_emails is set."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = null`: `default` is used when the caller passes nothing: `null` (not set).
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = length(var.budget_contact_emails) == 0 || var.budget_start_date != null`: `condition` is the rule: `length(var.budget_contact_emails) == 0 || var.budget_start_date != null` must be true.
- `error_message = "Set budget_start_date when budget_contact_emails is set."`: `error_message` is shown when the rule fails: "Set budget_start_date when budget_contact_emails is set."
- Closing lines: `}` end the blocks opened above.

**Lines 147 to 151**

```hcl
variable "tags" {
  description = "Extra tags merged into the standard ones."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Extra tags merged into the standard ones."`: `description` documents it: "Extra tags merged into the standard ones."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/budget/outputs.tf`

4 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "id" {
  description = "Budget resource id."
  value       = azurerm_consumption_budget_subscription.this.id
}
```

- `output "id" {`: Declares the output `id`.
- `description = "Budget resource id."`: `description` documents it: "Budget resource id."
- `value       = azurerm_consumption_budget_subscription.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_consumption_budget_subscription.this`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/budget/tests/budget.tftest.hcl`

29 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 9**

```hcl
variables {
  name            = "budget-orders"
  subscription_id = "00000000-0000-0000-0000-000000000000"
  amount          = 20
  start_date      = "2026-11-01T00:00:00Z"
  contact_emails  = ["owner@example.com"]
}
```

- `variables {`: Starts a `variables` block.
- `name            = "budget-orders"`: Sets the input variable `name` (Budget name) to the text `"budget-orders"`.
- `subscription_id = "00000000-0000-0000-0000-000000000000"`: Sets the input variable `subscription_id` (Subscription GUID the budget watches) to the text `"00000000-0000-0000-0000-000000000000"`.
- `amount          = 20`: Sets the input variable `amount` (Monthly amount in the billing currency) to the number `20`.
- `start_date      = "2026-11-01T00:00:00Z"`: Sets the input variable `start_date` (First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month) to the text `"2026-11-01T00:00:00Z"`.
- `contact_emails  = ["owner@example.com"]`: Sets the input variable `contact_emails` (Addresses that receive the alerts) to `["owner@example.com"]`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 18**

```hcl
run "alerts_at_80_and_100_percent_of_actual_spend" {
  command = plan

  assert {
    condition     = toset([for notification in azurerm_consumption_budget_subscription.this.notification : notification.threshold]) == toset([80, 100])
    error_message = "the budget must alert at 80 and 100 percent"
  }
}
```

- `run "alerts_at_80_and_100_percent_of_actual_spend" {`: Starts the test step `alerts at 80 and 100 percent of actual spend`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = toset([for notification in azurerm_consumption_budget_subscription.this.notification : notific`…: `condition` is the rule: `toset([for notification in azurerm_consumption_budget_subscription.this.notification : notification.threshold]) == toset([80, 100])` must be true.
- `error_message = "the budget must alert at 80 and 100 percent"`: `error_message` is shown when the rule fails: "the budget must alert at 80 and 100 percent"
- Closing lines: `}` end the blocks opened above.

**Lines 20 to 28**

```hcl
run "refuses_a_start_date_that_is_not_the_first_of_a_month" {
  command = plan

  variables {
    start_date = "2026-11-15T00:00:00Z"
  }

  expect_failures = [var.start_date]
}
```

- `run "refuses_a_start_date_that_is_not_the_first_of_a_month" {`: Starts the test step `refuses a start date that is not the first of a month`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `start_date = "2026-11-15T00:00:00Z"`: Sets the input variable `start_date` (First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month) to the text `"2026-11-15T00:00:00Z"`.
- `expect_failures = [var.start_date]`: Expects the failure of [var.start_date].
- Closing lines: `}` end the blocks opened above.

**Lines 30 to 38**

```hcl
run "refuses_a_budget_that_alerts_nobody" {
  command = plan

  variables {
    contact_emails = []
  }

  expect_failures = [var.contact_emails]
}
```

- `run "refuses_a_budget_that_alerts_nobody" {`: Starts the test step `refuses a budget that alerts nobody`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `contact_emails = []`: Sets the input variable `contact_emails` (Addresses that receive the alerts) to `[]`.
- `expect_failures = [var.contact_emails]`: Expects the failure of [var.contact_emails].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/budget/variables.tf`

41 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
variable "name" {
  description = "Budget name."
  type        = string
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Budget name."`: `description` documents it: "Budget name."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 6 to 14**

```hcl
variable "subscription_id" {
  description = "Subscription GUID the budget watches."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}
```

- `variable "subscription_id" {`: Declares the input variable `subscription_id`.
- `description = "Subscription GUID the budget watches."`: `description` documents it: "Subscription GUID the budget watches."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))`: `condition` is the rule: `can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))` must be true.
- `error_message = "subscription_id must be a GUID."`: `error_message` is shown when the rule fails: "subscription_id must be a GUID."
- Closing lines: `}` end the blocks opened above.

**Lines 16 to 24**

```hcl
variable "amount" {
  description = "Monthly amount in the billing currency."
  type        = number

  validation {
    condition     = var.amount > 0
    error_message = "amount must be positive."
  }
}
```

- `variable "amount" {`: Declares the input variable `amount`.
- `description = "Monthly amount in the billing currency."`: `description` documents it: "Monthly amount in the billing currency."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = var.amount > 0`: `condition` is the rule: `var.amount > 0` must be true.
- `error_message = "amount must be positive."`: `error_message` is shown when the rule fails: "amount must be positive."
- Closing lines: `}` end the blocks opened above.

**Lines 26 to 34**

```hcl
variable "start_date" {
  description = "First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.start_date))
    error_message = "start_date must be the first of a month at midnight UTC, for example 2026-11-01T00:00:00Z."
  }
}
```

- `variable "start_date" {`: Declares the input variable `start_date`.
- `description = "First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a m`…: `description` documents it: "First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.start_date))`: `condition` is the rule: `can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.start_date))` must be true.
- `error_message = "start_date must be the first of a month at midnight UTC, for example 2026-11-01T00:00:00Z."`: `error_message` is shown when the rule fails: "start_date must be the first of a month at midnight UTC, for example 2026-11-01T00:00:00Z."
- Closing lines: `}` end the blocks opened above.

**Lines 36 to 44**

```hcl
variable "contact_emails" {
  description = "Addresses that receive the alerts."
  type        = list(string)

  validation {
    condition     = length(var.contact_emails) > 0
    error_message = "At least one contact email is needed or the budget alerts nobody."
  }
}
```

- `variable "contact_emails" {`: Declares the input variable `contact_emails`.
- `description = "Addresses that receive the alerts."`: `description` documents it: "Addresses that receive the alerts."
- `type        = list(string)`: `type` limits what is accepted: `list(string)`: an ordered list of texts.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = length(var.contact_emails) > 0`: `condition` is the rule: `length(var.contact_emails) > 0` must be true.
- `error_message = "At least one contact email is needed or the budget alerts nobody."`: `error_message` is shown when the rule fails: "At least one contact email is needed or the budget alerts nobody."
- Closing lines: `}` end the blocks opened above.

**Lines 46 to 50**

```hcl
variable "thresholds_percent" {
  description = "Actual-spend percentages that send an alert."
  type        = list(number)
  default     = [80, 100]
}
```

- `variable "thresholds_percent" {`: Declares the input variable `thresholds_percent`.
- `description = "Actual-spend percentages that send an alert."`: `description` documents it: "Actual-spend percentages that send an alert."
- `type        = list(number)`: `type` limits what is accepted: the type `list(number)`
- `default     = [80, 100]`: `default` is used when the caller passes nothing: `[80, 100]`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/budget/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: The `terraform` block sets rules for Terraform itself: which version may run this code, which provider plug-ins it needs and where to find them, and where to keep state. Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: `required_providers` lists the provider plug-ins this code needs, each with `source` (where to download it from) and `version` (which releases are allowed). `~> 4.81` means "4.81 or newer, but below 5.0".
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/container_registry/outputs.tf`

12 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "id" {
  description = "Resource id; the scope for AcrPull."
  value       = azurerm_container_registry.this.id
}
```

- `output "id" {`: Declares the output `id`.
- `description = "Resource id; the scope for AcrPull."`: `description` documents it: "Resource id; the scope for AcrPull."
- `value       = azurerm_container_registry.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_container_registry.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "name" {
  description = "Registry name; `az acr build --registry` takes it."
  value       = azurerm_container_registry.this.name
}
```

- `output "name" {`: Declares the output `name`.
- `description = "Registry name; `az acr build --registry` takes it."`: `description` documents it: "Registry name; `az acr build --registry` takes it."
- `value       = azurerm_container_registry.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_container_registry.this`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
output "login_server" {
  description = "Registry host, for example myregistry.azurecr.io."
  value       = azurerm_container_registry.this.login_server
}
```

- `output "login_server" {`: Declares the output `login_server`.
- `description = "Registry host, for example myregistry.azurecr.io."`: `description` documents it: "Registry host, for example myregistry.azurecr.io."
- `value       = azurerm_container_registry.this.login_server`: `value` is what is exposed: the `login_server` of the resource `azurerm_container_registry.this`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/container_registry/tests/container_registry.tftest.hcl`

20 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 7**

```hcl
variables {
  name                = "acrorders12345"
  resource_group_name = "rg-test"
  location            = "westeurope"
}
```

- `variables {`: Starts a `variables` block.
- `name                = "acrorders12345"`: Sets the input variable `name` (Registry name: 5 to 50 letters and digits, globally unique) to the text `"acrorders12345"`.
- `resource_group_name = "rg-test"`: Sets the input variable `resource_group_name` (Resource group that holds the registry) to the text `"rg-test"`.
- `location            = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- Closing line: `}` ends the block opened above.

**Lines 9 to 16**

```hcl
run "has_no_admin_user_and_no_anonymous_pull" {
  command = plan

  assert {
    condition     = azurerm_container_registry.this.admin_enabled == false && azurerm_container_registry.this.anonymous_pull_enabled == false
    error_message = "the registry must not offer a shared password or anonymous pulls"
  }
}
```

- `run "has_no_admin_user_and_no_anonymous_pull" {`: Starts the test step `has no admin user and no anonymous pull`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_container_registry.this.admin_enabled == false && azurerm_container_registry.this.anon`…: `condition` is the rule: `azurerm_container_registry.this.admin_enabled == false && azurerm_container_registry.this.anonymous_pull_enabled == false` must be true.
- `error_message = "the registry must not offer a shared password or anonymous pulls"`: `error_message` is shown when the rule fails: "the registry must not offer a shared password or anonymous pulls"
- Closing lines: `}` end the blocks opened above.

**Lines 18 to 26**

```hcl
run "refuses_a_name_with_a_hyphen" {
  command = plan

  variables {
    name = "acr-orders"
  }

  expect_failures = [var.name]
}
```

- `run "refuses_a_name_with_a_hyphen" {`: Starts the test step `refuses a name with a hyphen`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `name = "acr-orders"`: Sets the input variable `name` (Registry name: 5 to 50 letters and digits, globally unique) to the text `"acr-orders"`.
- `expect_failures = [var.name]`: Expects the failure of [var.name].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/container_registry/variables.tf`

30 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 9**

```hcl
variable "name" {
  description = "Registry name: 5 to 50 letters and digits, globally unique."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.name))
    error_message = "A registry name has 5 to 50 letters and digits."
  }
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Registry name: 5 to 50 letters and digits, globally unique."`: `description` documents it: "Registry name: 5 to 50 letters and digits, globally unique."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.name))`: `condition` is the rule: `can(regex("^[a-zA-Z0-9]{5,50}$", var.name))` must be true.
- `error_message = "A registry name has 5 to 50 letters and digits."`: `error_message` is shown when the rule fails: "A registry name has 5 to 50 letters and digits."
- Closing lines: `}` end the blocks opened above.

**Lines 11 to 14**

```hcl
variable "resource_group_name" {
  description = "Resource group that holds the registry."
  type        = string
}
```

- `variable "resource_group_name" {`: Declares the input variable `resource_group_name`.
- `description = "Resource group that holds the registry."`: `description` documents it: "Resource group that holds the registry."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 21 to 30**

```hcl
variable "sku" {
  description = "Basic is the cheapest tier and enough to build and pull one image."
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku)
    error_message = "sku must be Basic, Standard or Premium."
  }
}
```

- `variable "sku" {`: Declares the input variable `sku`.
- `description = "Basic is the cheapest tier and enough to build and pull one image."`: `description` documents it: "Basic is the cheapest tier and enough to build and pull one image."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "Basic"`: `default` is used when the caller passes nothing: the text `"Basic"`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = contains(["Basic", "Standard", "Premium"], var.sku)`: `condition` is the rule: `contains(["Basic", "Standard", "Premium"], var.sku)` must be true.
- `error_message = "sku must be Basic, Standard or Premium."`: `error_message` is shown when the rule fails: "sku must be Basic, Standard or Premium."
- Closing lines: `}` end the blocks opened above.

**Lines 32 to 36**

```hcl
variable "tags" {
  description = "Tags applied to the registry."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Tags applied to the registry."`: `description` documents it: "Tags applied to the registry."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/container_registry/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/log_analytics/outputs.tf`

12 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "id" {
  description = "Resource id of the workspace; diagnostic settings and the container app environment take this."
  value       = azurerm_log_analytics_workspace.this.id
}
```

**New idea.** **Log Analytics** is Azure's store for logs and metrics, queried with the Kusto Query Language (KQL). A *diagnostic setting* tells a resource to send its logs there, so that, for example, every refused request to a vault can be found afterwards.

- `output "id" {`: Declares the output `id`.
- `description = "Resource id of the workspace; diagnostic settings and the container app environment take this."`: `description` documents it: "Resource id of the workspace; diagnostic settings and the container app environment take this."
- `value       = azurerm_log_analytics_workspace.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_log_analytics_workspace.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "name" {
  description = "Workspace name."
  value       = azurerm_log_analytics_workspace.this.name
}
```

- `output "name" {`: Declares the output `name`.
- `description = "Workspace name."`: `description` documents it: "Workspace name."
- `value       = azurerm_log_analytics_workspace.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_log_analytics_workspace.this`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
output "workspace_id" {
  description = "The workspace's customer id (a GUID, not a secret); `az monitor log-analytics query --workspace` takes it."
  value       = azurerm_log_analytics_workspace.this.workspace_id
}
```

- `output "workspace_id" {`: Declares the output `workspace_id`.
- `description = "The workspace's customer id (a GUID, not a secret); `az monitor log-analytics query --workspace`…: `description` documents it: "The workspace's customer id (a GUID, not a secret); `az monitor log-analytics query --workspace` takes it."
- `value       = azurerm_log_analytics_workspace.this.workspace_id`: `value` is what is exposed: the `workspace_id` of the resource `azurerm_log_analytics_workspace.this`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/log_analytics/tests/log_analytics.tftest.hcl`

20 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 7**

```hcl
variables {
  name                = "law-test"
  resource_group_name = "rg-test"
  location            = "westeurope"
}
```

- `variables {`: Starts a `variables` block.
- `name                = "law-test"`: Sets the input variable `name` (Workspace name, for example law-orders) to the text `"law-test"`.
- `resource_group_name = "rg-test"`: Sets the input variable `resource_group_name` (Resource group that holds the workspace) to the text `"rg-test"`.
- `location            = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- Closing line: `}` ends the block opened above.

**Lines 9 to 16**

```hcl
run "keeps_logs_for_the_free_retention_by_default" {
  command = plan

  assert {
    condition     = azurerm_log_analytics_workspace.this.retention_in_days == 30
    error_message = "the default retention must be the free 30 days"
  }
}
```

- `run "keeps_logs_for_the_free_retention_by_default" {`: Starts the test step `keeps logs for the free retention by default`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_log_analytics_workspace.this.retention_in_days == 30`: `condition` is the rule: `azurerm_log_analytics_workspace.this.retention_in_days == 30` must be true.
- `error_message = "the default retention must be the free 30 days"`: `error_message` is shown when the rule fails: "the default retention must be the free 30 days"
- Closing lines: `}` end the blocks opened above.

**Lines 18 to 26**

```hcl
run "refuses_retention_below_the_tier_minimum" {
  command = plan

  variables {
    retention_in_days = 7
  }

  expect_failures = [var.retention_in_days]
}
```

- `run "refuses_retention_below_the_tier_minimum" {`: Starts the test step `refuses retention below the tier minimum`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `retention_in_days = 7`: Sets the input variable `retention_in_days` (How long logs stay queryable. 30 days is the free retention of the PerGB2018 tier) to the number `7`.
- `expect_failures = [var.retention_in_days]`: Expects the failure of [var.retention_in_days].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/log_analytics/variables.tf`

26 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
variable "name" {
  description = "Workspace name, for example law-orders."
  type        = string
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Workspace name, for example law-orders."`: `description` documents it: "Workspace name, for example law-orders."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
variable "resource_group_name" {
  description = "Resource group that holds the workspace."
  type        = string
}
```

- `variable "resource_group_name" {`: Declares the input variable `resource_group_name`.
- `description = "Resource group that holds the workspace."`: `description` documents it: "Resource group that holds the workspace."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 16 to 25**

```hcl
variable "retention_in_days" {
  description = "How long logs stay queryable. 30 days is the free retention of the PerGB2018 tier."
  type        = number
  default     = 30

  validation {
    condition     = var.retention_in_days >= 30 && var.retention_in_days <= 730
    error_message = "retention_in_days must be between 30 and 730."
  }
}
```

- `variable "retention_in_days" {`: Declares the input variable `retention_in_days`.
- `description = "How long logs stay queryable. 30 days is the free retention of the PerGB2018 tier."`: `description` documents it: "How long logs stay queryable. 30 days is the free retention of the PerGB2018 tier."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 30`: `default` is used when the caller passes nothing: the number `30`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = var.retention_in_days >= 30 && var.retention_in_days <= 730`: `condition` is the rule: `var.retention_in_days >= 30 && var.retention_in_days <= 730` must be true.
- `error_message = "retention_in_days must be between 30 and 730."`: `error_message` is shown when the rule fails: "retention_in_days must be between 30 and 730."
- Closing lines: `}` end the blocks opened above.

**Lines 27 to 31**

```hcl
variable "tags" {
  description = "Tags applied to the workspace."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Tags applied to the workspace."`: `description` documents it: "Tags applied to the workspace."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/log_analytics/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/role_assignments/outputs.tf`

10 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
output "assignments" {
  description = "What was assigned, by key: principal, role and scope."
  value = {
    for key, assignment in azurerm_role_assignment.this : key => {
      principal_id = assignment.principal_id
      role         = assignment.role_definition_name
      scope        = assignment.scope
    }
  }
}
```

- `output "assignments" {`: Declares the output `assignments`.
- `description = "What was assigned, by key: principal, role and scope."`: `description` documents it: "What was assigned, by key: principal, role and scope."
- `value = {`: `value` is what is exposed: a group of named values that follows.
- `for key, assignment in azurerm_role_assignment.this : key => {`: Part of a `for` expression: `for key, assignment in azurerm_role_assignment.this : key => {`.
- `principal_id = assignment.principal_id`: Entry `principal_id`: `assignment.principal_id`.
- `role         = assignment.role_definition_name`: Entry `role`: `assignment.role_definition_name`.
- `scope        = assignment.scope`: Entry `scope`: `assignment.scope`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/role_assignments/tests/role_assignments.tftest.hcl`

87 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 11**

```hcl
variables {
  assignments = {
    blob = {
      principal_id = "22222222-2222-2222-2222-222222222222"
      role         = "Azure Service Bus Data Receiver"
      scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"
    }
  }
}
```

- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `blob = {`: Entry `blob`: a group of named values that follows.
- `principal_id = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role         = "Azure Service Bus Data Receiver"`: Entry `role`: the text `"Azure Service Bus Data Receiver"`.
- `scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft`…: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"`.
- Closing lines: `}` end the blocks opened above.

**Lines 13 to 25**

```hcl
run "accepts_a_queue_scope_and_assigns_without_the_directory_lookup" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.this["blob"].skip_service_principal_aad_check
    error_message = "a new service principal must be assigned by its type"
  }

  assert {
    condition     = azurerm_role_assignment.this["blob"].role_definition_name == "Azure Service Bus Data Receiver"
    error_message = "the role must be the one requested"
  }
}
```

- `run "accepts_a_queue_scope_and_assigns_without_the_directory_lookup" {`: Starts the test step `accepts a queue scope and assigns without the directory lookup`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_role_assignment.this["blob"].skip_service_principal_aad_check`: `condition` is the rule: `azurerm_role_assignment.this["blob"].skip_service_principal_aad_check` must be true.
- `error_message = "a new service principal must be assigned by its type"`: `error_message` is shown when the rule fails: "a new service principal must be assigned by its type"
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_role_assignment.this["blob"].role_definition_name == "Azure Service Bus Data Receiver"`: `condition` is the rule: `azurerm_role_assignment.this["blob"].role_definition_name == "Azure Service Bus Data Receiver"` must be true.
- `error_message = "the role must be the one requested"`: `error_message` is shown when the rule fails: "the role must be the one requested"
- Closing lines: `}` end the blocks opened above.

**Lines 27 to 41**

```hcl
run "refuses_a_resource_group_scope" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Azure Service Bus Data Receiver"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
      }
    }
  }

  expect_failures = [var.assignments]
}
```

- `run "refuses_a_resource_group_scope" {`: Starts the test step `refuses a resource group scope`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `blob = {`: Entry `blob`: a group of named values that follows.
- `principal_id = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role         = "Azure Service Bus Data Receiver"`: Entry `role`: the text `"Azure Service Bus Data Receiver"`.
- `scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"`: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"`.
- `expect_failures = [var.assignments]`: Expects the failure of [var.assignments].
- Closing lines: `}` end the blocks opened above.

**Lines 43 to 57**

```hcl
run "refuses_a_subscription_scope" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Reader"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000"
      }
    }
  }

  expect_failures = [var.assignments]
}
```

- `run "refuses_a_subscription_scope" {`: Starts the test step `refuses a subscription scope`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `blob = {`: Entry `blob`: a group of named values that follows.
- `principal_id = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role         = "Reader"`: Entry `role`: the text `"Reader"`.
- `scope        = "/subscriptions/00000000-0000-0000-0000-000000000000"`: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000"`.
- `expect_failures = [var.assignments]`: Expects the failure of [var.assignments].
- Closing lines: `}` end the blocks opened above.

**Lines 59 to 73**

```hcl
run "refuses_the_namespace_wide_owner_role" {
  command = plan

  variables {
    assignments = {
      owner = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Azure Service Bus Data Owner"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"
      }
    }
  }

  expect_failures = [var.assignments]
}
```

- `run "refuses_the_namespace_wide_owner_role" {`: Starts the test step `refuses the namespace wide owner role`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `owner = {`: Entry `owner`: a group of named values that follows.
- `principal_id = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role         = "Azure Service Bus Data Owner"`: Entry `role`: the text `"Azure Service Bus Data Owner"`.
- `scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft`…: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"`.
- `expect_failures = [var.assignments]`: Expects the failure of [var.assignments].
- Closing lines: `}` end the blocks opened above.

**Lines 75 to 89**

```hcl
run "refuses_a_management_role" {
  command = plan

  variables {
    assignments = {
      owner = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Contributor"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"
      }
    }
  }

  expect_failures = [var.assignments]
}
```

- `run "refuses_a_management_role" {`: Starts the test step `refuses a management role`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `owner = {`: Entry `owner`: a group of named values that follows.
- `principal_id = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role         = "Contributor"`: Entry `role`: the text `"Contributor"`.
- `scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft`…: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"`.
- `expect_failures = [var.assignments]`: Expects the failure of [var.assignments].
- Closing lines: `}` end the blocks opened above.

**Lines 91 to 106**

```hcl
run "refuses_an_unknown_principal_type" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id   = "22222222-2222-2222-2222-222222222222"
        role           = "Reader"
        scope          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"
        principal_type = "Robot"
      }
    }
  }

  expect_failures = [var.assignments]
}
```

- `run "refuses_an_unknown_principal_type" {`: Starts the test step `refuses an unknown principal type`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `assignments = {`: Sets the input variable `assignments` to a group of named values that follows.
- `blob = {`: Entry `blob`: a group of named values that follows.
- `principal_id   = "22222222-2222-2222-2222-222222222222"`: Entry `principal_id`: the text `"22222222-2222-2222-2222-222222222222"`.
- `role           = "Reader"`: Entry `role`: the text `"Reader"`.
- `scope          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microso`…: Entry `scope`: the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"`.
- `principal_type = "Robot"`: Entry `principal_type`: the text `"Robot"`.
- `expect_failures = [var.assignments]`: Expects the failure of [var.assignments].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/role_assignments/variables.tf`

31 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 28**

```hcl
variable "assignments" {
  description = <<-EOT
    Role assignments by a stable key. Each entry names the principal's object id (not its client id), the built-in
    role and the scope. The scope must be a single resource or sub-resource: a subscription or a resource group is
    refused, which is the "narrowest scope that works" rule written as code.
  EOT
  type = map(object({
    principal_id   = string
    role           = string
    scope          = string
    principal_type = optional(string, "ServicePrincipal")
  }))

  validation {
    condition = alltrue([
      for assignment in var.assignments :
      can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+/.+", assignment.scope))
    ])
    error_message = "Every scope must be a resource (/subscriptions/.../resourceGroups/.../providers/...), never a subscription or a resource group."
  }

  validation {
    condition = alltrue([
      for assignment in var.assignments :
      contains(["ServicePrincipal", "User", "Group"], assignment.principal_type)
    ])
    error_message = "principal_type must be ServicePrincipal, User or Group."
  }
```

- `variable "assignments" {`: Declares the input variable `assignments`.
- `description = <<-EOT`: `description` documents it: <<-EOT `<<-EOT ... EOT` (a **heredoc**) writes a multi-line text; `<<-` lets the lines be indented.
- `Role assignments by a stable key. Each entry names the principal's object id (not its client id), the built-in`: continues the structure above.
- `role and the scope. The scope must be a single resource or sub-resource: a subscription or a resource group is`: continues the structure above.
- `refused, which is the "narrowest scope that works" rule written as code.`: continues the structure above.
- `EOT`: continues the structure above.
- `type = map(object({`: `type` limits what is accepted: `map(object({...}))`: a set of named records, each with the fields listed.
- `principal_id   = string`: Entry `principal_id`: `string`.
- `role           = string`: Entry `role`: `string`.
- `scope          = string`: Entry `scope`: `string`.
- `principal_type = optional(string, "ServicePrincipal")`: Entry `principal_type`: `optional(string, "ServicePrincipal")`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition = alltrue([`: `condition` is the rule: `alltrue([` must be true.
- `for assignment in var.assignments :`: Part of a `for` expression: `for assignment in var.assignments :`.
- `can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+/.+", assignment.scope))`: Item: `can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+/.+", assignment.scope))`.
- `error_message = "Every scope must be a resource (/subscriptions/.../resourceGroups/.../providers/...), never a`…: `error_message` is shown when the rule fails: "Every scope must be a resource (/subscriptions/.../resourceGroups/.../providers/...), never a subscription or a resource group."
- `validation {`: Starts a rule the input value must satisfy.
- `condition = alltrue([`: `condition` is the rule: `alltrue([` must be true.
- `for assignment in var.assignments :`: Part of a `for` expression: `for assignment in var.assignments :`.
- `contains(["ServicePrincipal", "User", "Group"], assignment.principal_type)`: Item: `contains(["ServicePrincipal", "User", "Group"], assignment.principal_type)`.
- `error_message = "principal_type must be ServicePrincipal, User or Group."`: `error_message` is shown when the rule fails: "principal_type must be ServicePrincipal, User or Group."
- Closing lines: `}))`, `])`, `}` end the blocks opened above.

**Lines 30 to 34**

```hcl
  validation {
    condition     = !anytrue([for assignment in var.assignments : contains(["Owner", "Contributor", "User Access Administrator", "Azure Service Bus Data Owner"], assignment.role)])
    error_message = "Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner are too wide; this project assigns the Data Sender and Data Receiver roles on single queues."
  }
}
```

- `validation {`: Starts a rule the input value must satisfy.
- `condition     = !anytrue([for assignment in var.assignments : contains(["Owner", "Contributor", "User Access A`…: `condition` is the rule: `!anytrue([for assignment in var.assignments : contains(["Owner", "Contributor", "User Access Administrator", "Azure Service Bus Data Owner"], assignment.role)])` must be true. `anytrue(list)` is true when at least one item is true.
- `error_message = "Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner are too wide; `…: `error_message` is shown when the rule fails: "Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner are too wide; this project assigns the Data Sender and Data Receiver roles on single queues."
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/role_assignments/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/servicebus/outputs.tf`

20 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "id" {
  description = "Namespace resource id."
  value       = azurerm_servicebus_namespace.this.id
}
```

- `output "id" {`: Declares the output `id`.
- `description = "Namespace resource id."`: `description` documents it: "Namespace resource id."
- `value       = azurerm_servicebus_namespace.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_servicebus_namespace.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "name" {
  description = "Namespace name."
  value       = azurerm_servicebus_namespace.this.name
}
```

- `output "name" {`: Declares the output `name`.
- `description = "Namespace name."`: `description` documents it: "Namespace name."
- `value       = azurerm_servicebus_namespace.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_servicebus_namespace.this`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
output "fully_qualified_namespace" {
  description = "Host name the SDK connects to, for example mybus.servicebus.windows.net: the programs' SB_NAMESPACE."
  value       = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
}
```

**New idea.** An **SDK** (software development kit) or *client library* is a package of ready-made code that talks to a service for you. The Azure ones turn calls such as "read this secret" into the correct web requests, add the access token and retry transient failures.

- `output "fully_qualified_namespace" {`: Declares the output `fully_qualified_namespace`.
- `description = "Host name the SDK connects to, for example mybus.servicebus.windows.net: the programs' SB_NAMES`…: `description` documents it: "Host name the SDK connects to, for example mybus.servicebus.windows.net: the programs' SB_NAMESPACE."
- `value       = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"`: `value` is what is exposed: text built from the pieces the `name` of the resource `azurerm_servicebus_namespace.this`.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
output "queue_ids" {
  description = "Queue resource ids by name: the narrowest scope for the Data Sender and Data Receiver roles."
  value       = { for name, queue in azurerm_servicebus_queue.this : name => queue.id }
}
```

- `output "queue_ids" {`: Declares the output `queue_ids`.
- `description = "Queue resource ids by name: the narrowest scope for the Data Sender and Data Receiver roles."`: `description` documents it: "Queue resource ids by name: the narrowest scope for the Data Sender and Data Receiver roles."
- `value       = { for name, queue in azurerm_servicebus_queue.this : name => queue.id }`: `value` is what is exposed: the resource `azurerm_servicebus_queue.this`.
- Closing line: `}` ends the block opened above.

**Lines 21 to 24**

```hcl
output "queue_names" {
  description = "Queue names."
  value       = keys(azurerm_servicebus_queue.this)
}
```

- `output "queue_names" {`: Declares the output `queue_names`.
- `description = "Queue names."`: `description` documents it: "Queue names."
- `value       = keys(azurerm_servicebus_queue.this)`: `value` is what is exposed: the resource `azurerm_servicebus_queue.this`. `keys(map)` lists a map's keys.
- Closing line: `}` ends the block opened above.

#### `infra/modules/servicebus/tests/servicebus.tftest.hcl`

85 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 12**

```hcl
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
```

- `variables {`: Starts a `variables` block.
- `name                       = "sb-orders-abcde"`: Sets the input variable `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter) to the text `"sb-orders-abcde"`.
- `resource_group_name        = "rg-test"`: Sets the input variable `resource_group_name` (Resource group that holds the namespace) to the text `"rg-test"`.
- `location                   = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- `log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/provi`…: Sets the input variable `log_analytics_workspace_id` (Workspace that receives the operational logs and metrics) to the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.OperationalInsights/workspaces/law-test"`.
- `queues = {`: Sets the input variable `queues` to a group of named values that follows.
- `orders          = {}`: Entry `orders`: `{}`.
- `orders-sessions = { requires_session = true }`: Entry `orders-sessions`: `{ requires_session = true }`.
- Closing lines: `}` end the blocks opened above.

**Lines 14 to 26**

```hcl
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
```

**New idea.** **TLS** is the protocol that encrypts a network connection and proves who is on the other end, which is what the `s` in `https` stands for. The server proves its identity with a **certificate**, a signed document that names the server and carries its public key; a client refuses a certificate it cannot trust.

- `run "is_standard_tier_and_accepts_only_entra_authentication" {`: Starts the test step `is standard tier and accepts only entra authentication`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_servicebus_namespace.this.sku == "Standard"`: `condition` is the rule: `azurerm_servicebus_namespace.this.sku == "Standard"` must be true.
- `error_message = "sessions need the Standard tier"`: `error_message` is shown when the rule fails: "sessions need the Standard tier"
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_servicebus_namespace.this.local_auth_enabled == false && azurerm_servicebus_namespace.`…: `condition` is the rule: `azurerm_servicebus_namespace.this.local_auth_enabled == false && azurerm_servicebus_namespace.this.minimum_tls_version == "1.2"` must be true.
- `error_message = "shared access keys must be off and TLS 1.2 required"`: `error_message` is shown when the rule fails: "shared access keys must be off and TLS 1.2 required"
- Closing lines: `}` end the blocks opened above.

**Lines 28 to 40**

```hcl
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
```

- `run "queues_follow_the_lesson_a_30_second_lock_and_ten_deliveries" {`: Starts the test step `queues follow the lesson a 30 second lock and ten deliveries`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = alltrue([for queue in azurerm_servicebus_queue.this : queue.lock_duration == "PT30S" && queue.`…: `condition` is the rule: `alltrue([for queue in azurerm_servicebus_queue.this : queue.lock_duration == "PT30S" && queue.max_delivery_count == 10])` must be true.
- `error_message = "every queue needs a 30 s lock and a maximum delivery count of 10"`: `error_message` is shown when the rule fails: "every queue needs a 30 s lock and a maximum delivery count of 10"
- `assert {`: Starts an `assert` block.
- `condition     = alltrue([for queue in azurerm_servicebus_queue.this : queue.dead_lettering_on_message_expirati`…: `condition` is the rule: `alltrue([for queue in azurerm_servicebus_queue.this : queue.dead_lettering_on_message_expiration])` must be true.
- `error_message = "expired messages must be dead-lettered, not dropped"`: `error_message` is shown when the rule fails: "expired messages must be dead-lettered, not dropped"
- Closing lines: `}` end the blocks opened above.

**Lines 42 to 49**

```hcl
run "only_the_session_queue_requires_sessions" {
  command = plan

  assert {
    condition     = azurerm_servicebus_queue.this["orders-sessions"].requires_session && !azurerm_servicebus_queue.this["orders"].requires_session
    error_message = "orders-sessions requires sessions, orders does not"
  }
}
```

- `run "only_the_session_queue_requires_sessions" {`: Starts the test step `only the session queue requires sessions`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_servicebus_queue.this["orders-sessions"].requires_session && !azurerm_servicebus_queue`…: `condition` is the rule: `azurerm_servicebus_queue.this["orders-sessions"].requires_session && !azurerm_servicebus_queue.this["orders"].requires_session` must be true.
- `error_message = "orders-sessions requires sessions, orders does not"`: `error_message` is shown when the rule fails: "orders-sessions requires sessions, orders does not"
- Closing lines: `}` end the blocks opened above.

**Lines 51 to 58**

```hcl
run "logs_and_metrics_go_to_the_workspace" {
  command = plan

  assert {
    condition     = one(azurerm_monitor_diagnostic_setting.namespace.enabled_log).category == "OperationalLogs"
    error_message = "operational logs must be enabled"
  }
}
```

- `run "logs_and_metrics_go_to_the_workspace" {`: Starts the test step `logs and metrics go to the workspace`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = one(azurerm_monitor_diagnostic_setting.namespace.enabled_log).category == "OperationalLogs"`: `condition` is the rule: `one(azurerm_monitor_diagnostic_setting.namespace.enabled_log).category == "OperationalLogs"` must be true.
- `error_message = "operational logs must be enabled"`: `error_message` is shown when the rule fails: "operational logs must be enabled"
- Closing lines: `}` end the blocks opened above.

**Lines 60 to 67**

```hcl
run "no_alert_without_recipients" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_metric_alert.dead_letters) == 0 && length(azurerm_monitor_action_group.dead_letters) == 0
    error_message = "an alert that mails nobody must not be created"
  }
}
```

- `run "no_alert_without_recipients" {`: Starts the test step `no alert without recipients`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = length(azurerm_monitor_metric_alert.dead_letters) == 0 && length(azurerm_monitor_action_group.`…: `condition` is the rule: `length(azurerm_monitor_metric_alert.dead_letters) == 0 && length(azurerm_monitor_action_group.dead_letters) == 0` must be true.
- `error_message = "an alert that mails nobody must not be created"`: `error_message` is shown when the rule fails: "an alert that mails nobody must not be created"
- Closing lines: `}` end the blocks opened above.

**Lines 69 to 80**

```hcl
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
```

- `run "alerts_on_any_dead_letter_when_recipients_are_given" {`: Starts the test step `alerts on any dead letter when recipients are given`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `alert_email_addresses = ["owner@example.com"]`: Sets the input variable `alert_email_addresses` (Recipients of the dead-letter alert. Empty creates no alert) to `["owner@example.com"]`.
- `assert {`: Starts an `assert` block.
- `condition     = one(azurerm_monitor_metric_alert.dead_letters[0].criteria).metric_name == "DeadletteredMessage`…: `condition` is the rule: `one(azurerm_monitor_metric_alert.dead_letters[0].criteria).metric_name == "DeadletteredMessages" && one(azurerm_monitor_metric_alert.dead_letters[0].criteria).threshold == 0` must be true.
- `error_message = "the alert must fire when the dead-letter count is above zero"`: `error_message` is shown when the rule fails: "the alert must fire when the dead-letter count is above zero"
- Closing lines: `}` end the blocks opened above.

**Lines 82 to 90**

```hcl
run "refuses_a_delivery_count_of_zero" {
  command = plan

  variables {
    queues = { orders = { max_delivery_count = 0 } }
  }

  expect_failures = [var.queues]
}
```

- `run "refuses_a_delivery_count_of_zero" {`: Starts the test step `refuses a delivery count of zero`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `queues = { orders = { max_delivery_count = 0 } }`: Sets the input variable `queues` to `{ orders = { max_delivery_count = 0 } }`.
- `expect_failures = [var.queues]`: Expects the failure of [var.queues].
- Closing lines: `}` end the blocks opened above.

**Lines 92 to 100**

```hcl
run "refuses_a_lock_duration_that_is_not_an_iso_duration" {
  command = plan

  variables {
    queues = { orders = { lock_duration = "30 seconds" } }
  }

  expect_failures = [var.queues]
}
```

- `run "refuses_a_lock_duration_that_is_not_an_iso_duration" {`: Starts the test step `refuses a lock duration that is not an iso duration`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `queues = { orders = { lock_duration = "30 seconds" } }`: Sets the input variable `queues` to `{ orders = { lock_duration = "30 seconds" } }`.
- `expect_failures = [var.queues]`: Expects the failure of [var.queues].
- Closing lines: `}` end the blocks opened above.

**Lines 102 to 110**

```hcl
run "refuses_a_short_name" {
  command = plan

  variables {
    name = "sb"
  }

  expect_failures = [var.name]
}
```

- `run "refuses_a_short_name" {`: Starts the test step `refuses a short name`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `name = "sb"`: Sets the input variable `name` (Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter) to the text `"sb"`.
- `expect_failures = [var.name]`: Expects the failure of [var.name].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/servicebus/variables.tf`

50 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 9**

```hcl
variable "name" {
  description = "Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$", var.name))
    error_message = "A namespace name has 6 to 50 characters, starts with a letter, ends with a letter or digit and holds letters, digits and hyphens."
  }
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter."`: `description` documents it: "Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$", var.name))`: `condition` is the rule: `can(regex("^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$", var.name))` must be true.
- `error_message = "A namespace name has 6 to 50 characters, starts with a letter, ends with a letter or digit an`…: `error_message` is shown when the rule fails: "A namespace name has 6 to 50 characters, starts with a letter, ends with a letter or digit and holds letters, digits and hyphens."
- Closing lines: `}` end the blocks opened above.

**Lines 11 to 14**

```hcl
variable "resource_group_name" {
  description = "Resource group that holds the namespace."
  type        = string
}
```

- `variable "resource_group_name" {`: Declares the input variable `resource_group_name`.
- `description = "Resource group that holds the namespace."`: `description` documents it: "Resource group that holds the namespace."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 21 to 42**

```hcl
variable "queues" {
  description = <<-EOT
    Queues by name. Defaults follow the lesson: a 30-second lock, ten deliveries before the dead-letter queue.
    `requires_session` cannot be changed on an existing queue, which is why the session queue is a second queue.
  EOT
  type = map(object({
    lock_duration       = optional(string, "PT30S")
    max_delivery_count  = optional(number, 10)
    requires_session    = optional(bool, false)
    default_message_ttl = optional(string, "P1D")
  }))

  validation {
    condition     = alltrue([for queue in var.queues : queue.lock_duration != null && can(regex("^PT([0-9]+M)?([0-9]+S)?$", queue.lock_duration))])
    error_message = "lock_duration must be an ISO 8601 duration of at most 5 minutes, such as PT30S."
  }

  validation {
    condition     = alltrue([for queue in var.queues : queue.max_delivery_count >= 1 && queue.max_delivery_count <= 2000])
    error_message = "max_delivery_count must be between 1 and 2000."
  }
}
```

- `variable "queues" {`: Declares the input variable `queues`.
- `description = <<-EOT`: `description` documents it: <<-EOT
- `Queues by name. Defaults follow the lesson: a 30-second lock, ten deliveries before the dead-letter queue.`: continues the structure above.
- ``requires_session` cannot be changed on an existing queue, which is why the session queue is a second queue.`: continues the structure above.
- `EOT`: continues the structure above.
- `type = map(object({`: `type` limits what is accepted: `map(object({...}))`: a set of named records, each with the fields listed.
- `lock_duration       = optional(string, "PT30S")`: Entry `lock_duration`: `optional(string, "PT30S")`.
- `max_delivery_count  = optional(number, 10)`: Entry `max_delivery_count`: `optional(number, 10)`.
- `requires_session    = optional(bool, false)`: Entry `requires_session`: `optional(bool, false)`.
- `default_message_ttl = optional(string, "P1D")`: Entry `default_message_ttl`: `optional(string, "P1D")`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = alltrue([for queue in var.queues : queue.lock_duration != null && can(regex("^PT([0-9]+M)?([0-`…: `condition` is the rule: `alltrue([for queue in var.queues : queue.lock_duration != null && can(regex("^PT([0-9]+M)?([0-9]+S)?$", queue.lock_duration))])` must be true.
- `error_message = "lock_duration must be an ISO 8601 duration of at most 5 minutes, such as PT30S."`: `error_message` is shown when the rule fails: "lock_duration must be an ISO 8601 duration of at most 5 minutes, such as PT30S."
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = alltrue([for queue in var.queues : queue.max_delivery_count >= 1 && queue.max_delivery_count <`…: `condition` is the rule: `alltrue([for queue in var.queues : queue.max_delivery_count >= 1 && queue.max_delivery_count <= 2000])` must be true.
- `error_message = "max_delivery_count must be between 1 and 2000."`: `error_message` is shown when the rule fails: "max_delivery_count must be between 1 and 2000."
- Closing lines: `}))`, `}` end the blocks opened above.

**Lines 44 to 47**

```hcl
variable "log_analytics_workspace_id" {
  description = "Workspace that receives the operational logs and metrics."
  type        = string
}
```

- `variable "log_analytics_workspace_id" {`: Declares the input variable `log_analytics_workspace_id`.
- `description = "Workspace that receives the operational logs and metrics."`: `description` documents it: "Workspace that receives the operational logs and metrics."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 49 to 53**

```hcl
variable "alert_email_addresses" {
  description = "Recipients of the dead-letter alert. Empty creates no alert."
  type        = list(string)
  default     = []
}
```

- `variable "alert_email_addresses" {`: Declares the input variable `alert_email_addresses`.
- `description = "Recipients of the dead-letter alert. Empty creates no alert."`: `description` documents it: "Recipients of the dead-letter alert. Empty creates no alert."
- `type        = list(string)`: `type` limits what is accepted: `list(string)`: an ordered list of texts.
- `default     = []`: `default` is used when the caller passes nothing: `[]`.
- Closing line: `}` ends the block opened above.

**Lines 55 to 59**

```hcl
variable "tags" {
  description = "Tags applied to the namespace and the alert."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Tags applied to the namespace and the alert."`: `description` documents it: "Tags applied to the namespace and the alert."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/servicebus/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/user_assigned_identity/outputs.tf`

16 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "id" {
  description = "Resource id; a container app lists it under `identity_ids`."
  value       = azurerm_user_assigned_identity.this.id
}
```

- `output "id" {`: Declares the output `id`.
- `description = "Resource id; a container app lists it under `identity_ids`."`: `description` documents it: "Resource id; a container app lists it under `identity_ids`."
- `value       = azurerm_user_assigned_identity.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_user_assigned_identity.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "principal_id" {
  description = "Object id of the identity's service principal; role assignments take this, not the client id."
  value       = azurerm_user_assigned_identity.this.principal_id
}
```

- `output "principal_id" {`: Declares the output `principal_id`.
- `description = "Object id of the identity's service principal; role assignments take this, not the client id."`: `description` documents it: "Object id of the identity's service principal; role assignments take this, not the client id."
- `value       = azurerm_user_assigned_identity.this.principal_id`: `value` is what is exposed: the `principal_id` of the resource `azurerm_user_assigned_identity.this`.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
output "client_id" {
  description = "Application id; the app's AZURE_CLIENT_ID. It names the identity and is not a secret."
  value       = azurerm_user_assigned_identity.this.client_id
}
```

- `output "client_id" {`: Declares the output `client_id`.
- `description = "Application id; the app's AZURE_CLIENT_ID. It names the identity and is not a secret."`: `description` documents it: "Application id; the app's AZURE_CLIENT_ID. It names the identity and is not a secret."
- `value       = azurerm_user_assigned_identity.this.client_id`: `value` is what is exposed: the `client_id` of the resource `azurerm_user_assigned_identity.this`.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
output "name" {
  description = "Identity name."
  value       = azurerm_user_assigned_identity.this.name
}
```

- `output "name" {`: Declares the output `name`.
- `description = "Identity name."`: `description` documents it: "Identity name."
- `value       = azurerm_user_assigned_identity.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_user_assigned_identity.this`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/user_assigned_identity/tests/user_assigned_identity.tftest.hcl`

14 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 8**

```hcl
variables {
  name                = "id-orders-worker"
  resource_group_name = "rg-test"
  location            = "westeurope"
  tags                = { project = "test" }
}
```

- `variables {`: Starts a `variables` block.
- `name                = "id-orders-worker"`: Sets the input variable `name` (Identity name, for example id-orders-worker) to the text `"id-orders-worker"`.
- `resource_group_name = "rg-test"`: Sets the input variable `resource_group_name` (Resource group that holds the identity) to the text `"rg-test"`.
- `location            = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- `tags                = { project = "test" }`: Sets the input variable `tags` (Tags applied to the identity) to `{ project = "test" }`.
- Closing line: `}` ends the block opened above.

**Lines 10 to 17**

```hcl
run "creates_a_user_assigned_identity_with_the_given_name_and_tags" {
  command = plan

  assert {
    condition     = azurerm_user_assigned_identity.this.name == "id-orders-worker" && azurerm_user_assigned_identity.this.tags["project"] == "test"
    error_message = "the identity must carry the requested name and tags"
  }
}
```

- `run "creates_a_user_assigned_identity_with_the_given_name_and_tags" {`: Starts the test step `creates a user assigned identity with the given name and tags`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = azurerm_user_assigned_identity.this.name == "id-orders-worker" && azurerm_user_assigned_identi`…: `condition` is the rule: `azurerm_user_assigned_identity.this.name == "id-orders-worker" && azurerm_user_assigned_identity.this.tags["project"] == "test"` must be true.
- `error_message = "the identity must carry the requested name and tags"`: `error_message` is shown when the rule fails: "the identity must carry the requested name and tags"
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/user_assigned_identity/variables.tf`

17 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
variable "name" {
  description = "Identity name, for example id-orders-worker."
  type        = string
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Identity name, for example id-orders-worker."`: `description` documents it: "Identity name, for example id-orders-worker."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
variable "resource_group_name" {
  description = "Resource group that holds the identity."
  type        = string
}
```

- `variable "resource_group_name" {`: Declares the input variable `resource_group_name`.
- `description = "Resource group that holds the identity."`: `description` documents it: "Resource group that holds the identity."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 16 to 20**

```hcl
variable "tags" {
  description = "Tags applied to the identity."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Tags applied to the identity."`: `description` documents it: "Tags applied to the identity."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/user_assigned_identity/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/worker_app/outputs.tf`

8 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
output "name" {
  description = "Container app name; `az containerapp exec` and `az containerapp logs show` take it."
  value       = azurerm_container_app.this.name
}
```

- `output "name" {`: Declares the output `name`.
- `description = "Container app name; `az containerapp exec` and `az containerapp logs show` take it."`: `description` documents it: "Container app name; `az containerapp exec` and `az containerapp logs show` take it."
- `value       = azurerm_container_app.this.name`: `value` is what is exposed: the `name` of the resource `azurerm_container_app.this`.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
output "environment_id" {
  description = "Container Apps environment id."
  value       = azurerm_container_app_environment.this.id
}
```

- `output "environment_id" {`: Declares the output `environment_id`.
- `description = "Container Apps environment id."`: `description` documents it: "Container Apps environment id."
- `value       = azurerm_container_app_environment.this.id`: `value` is what is exposed: the `id` of the resource `azurerm_container_app_environment.this`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/worker_app/tests/worker_app.tftest.hcl`

102 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
mock_provider "azurerm" {}
```

- `mock_provider "azurerm" {}`: An empty `mock_provider` block for `azurerm`: the fake invents every value, with no special settings.

**Lines 3 to 18**

```hcl
variables {
  name                       = "ca-orders-worker"
  environment_name           = "cae-orders"
  resource_group_name        = "rg-test"
  location                   = "westeurope"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.OperationalInsights/workspaces/law-test"
  image                      = "acrtest.azurecr.io/azure-service-bus-worker:0.1.0"
  worker_identity_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-worker"
  pull_identity_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-pull"
  registry_server            = "acrtest.azurecr.io"
  env = {
    AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
    SB_NAMESPACE    = "sb-orders-abcde.servicebus.windows.net"
    SB_QUEUE        = "orders"
  }
}
```

- `variables {`: Starts a `variables` block.
- `name                       = "ca-orders-worker"`: Sets the input variable `name` (Container app name, for example ca-orders-worker) to the text `"ca-orders-worker"`.
- `environment_name           = "cae-orders"`: Sets the input variable `environment_name` (Container Apps environment name) to the text `"cae-orders"`.
- `resource_group_name        = "rg-test"`: Sets the input variable `resource_group_name` (Resource group that holds both) to the text `"rg-test"`.
- `location                   = "westeurope"`: Sets the input variable `location` (Azure region) to the text `"westeurope"`.
- `log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/provi`…: Sets the input variable `log_analytics_workspace_id` (Workspace that receives the console logs) to the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.OperationalInsights/workspaces/law-test"`.
- `image                      = "acrtest.azurecr.io/azure-service-bus-worker:0.1.0"`: Sets the input variable `image` (Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest) to the text `"acrtest.azurecr.io/azure-service-bus-worker:0.1.0"`.
- `worker_identity_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/provi`…: Sets the input variable `worker_identity_id` (Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)) to the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-worker"`.
- `pull_identity_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/provi`…: Sets the input variable `pull_identity_id` (Resource id of the identity that only pulls the image (AcrPull on the registry)) to the text `"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-pull"`.
- `registry_server            = "acrtest.azurecr.io"`: Sets the input variable `registry_server` (Registry host, for example myregistry.azurecr.io) to the text `"acrtest.azurecr.io"`.
- `env = {`: Sets the input variable `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value) to a group of named values that follows.
- `AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"`: Entry `AZURE_CLIENT_ID`: the text `"00000000-0000-0000-0000-000000000000"`.
- `SB_NAMESPACE    = "sb-orders-abcde.servicebus.windows.net"`: Entry `SB_NAMESPACE`: the text `"sb-orders-abcde.servicebus.windows.net"`.
- `SB_QUEUE        = "orders"`: Entry `SB_QUEUE`: the text `"orders"`.
- Closing lines: `}` end the blocks opened above.

**Lines 20 to 37**

```hcl
run "carries_no_secret_blocks_and_only_the_given_plain_variables" {
  command = plan

  assert {
    condition     = length(azurerm_container_app.this.secret) == 0
    error_message = "the worker must hold no secret"
  }

  assert {
    condition     = toset([for variable in one(one(azurerm_container_app.this.template).container).env : variable.name]) == toset(["AZURE_CLIENT_ID", "SB_NAMESPACE", "SB_QUEUE"])
    error_message = "only the given variables may be set"
  }

  assert {
    condition     = alltrue([for variable in one(one(azurerm_container_app.this.template).container).env : variable.secret_name == null])
    error_message = "no variable may reference a secret"
  }
}
```

- `run "carries_no_secret_blocks_and_only_the_given_plain_variables" {`: Starts the test step `carries no secret blocks and only the given plain variables`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = length(azurerm_container_app.this.secret) == 0`: `condition` is the rule: `length(azurerm_container_app.this.secret) == 0` must be true.
- `error_message = "the worker must hold no secret"`: `error_message` is shown when the rule fails: "the worker must hold no secret"
- `assert {`: Starts an `assert` block.
- `condition     = toset([for variable in one(one(azurerm_container_app.this.template).container).env : variable.`…: `condition` is the rule: `toset([for variable in one(one(azurerm_container_app.this.template).container).env : variable.name]) == toset(["AZURE_CLIENT_ID", "SB_NAMESPACE", "SB_QUEUE"])` must be true.
- `error_message = "only the given variables may be set"`: `error_message` is shown when the rule fails: "only the given variables may be set"
- `assert {`: Starts an `assert` block.
- `condition     = alltrue([for variable in one(one(azurerm_container_app.this.template).container).env : variabl`…: `condition` is the rule: `alltrue([for variable in one(one(azurerm_container_app.this.template).container).env : variable.secret_name == null])` must be true.
- `error_message = "no variable may reference a secret"`: `error_message` is shown when the rule fails: "no variable may reference a secret"
- Closing lines: `}` end the blocks opened above.

**Lines 39 to 46**

```hcl
run "has_no_ingress_so_nothing_can_connect_to_the_worker" {
  command = plan

  assert {
    condition     = length(azurerm_container_app.this.ingress) == 0
    error_message = "the worker pulls from the queue; it must not be reachable"
  }
}
```

- `run "has_no_ingress_so_nothing_can_connect_to_the_worker" {`: Starts the test step `has no ingress so nothing can connect to the worker`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = length(azurerm_container_app.this.ingress) == 0`: `condition` is the rule: `length(azurerm_container_app.this.ingress) == 0` must be true.
- `error_message = "the worker pulls from the queue; it must not be reachable"`: `error_message` is shown when the rule fails: "the worker pulls from the queue; it must not be reachable"
- Closing lines: `}` end the blocks opened above.

**Lines 48 to 60**

```hcl
run "runs_as_both_identities_and_pulls_with_the_pull_identity" {
  command = plan

  assert {
    condition     = length(one(azurerm_container_app.this.identity).identity_ids) == 2
    error_message = "the worker and pull identities must both be attached"
  }

  assert {
    condition     = one(azurerm_container_app.this.registry).identity == var.pull_identity_id
    error_message = "the registry must be reached with the pull identity"
  }
}
```

- `run "runs_as_both_identities_and_pulls_with_the_pull_identity" {`: Starts the test step `runs as both identities and pulls with the pull identity`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = length(one(azurerm_container_app.this.identity).identity_ids) == 2`: `condition` is the rule: `length(one(azurerm_container_app.this.identity).identity_ids) == 2` must be true.
- `error_message = "the worker and pull identities must both be attached"`: `error_message` is shown when the rule fails: "the worker and pull identities must both be attached"
- `assert {`: Starts an `assert` block.
- `condition     = one(azurerm_container_app.this.registry).identity == var.pull_identity_id`: `condition` is the rule: `one(azurerm_container_app.this.registry).identity == var.pull_identity_id` must be true.
- `error_message = "the registry must be reached with the pull identity"`: `error_message` is shown when the rule fails: "the registry must be reached with the pull identity"
- Closing lines: `}` end the blocks opened above.

**Lines 62 to 74**

```hcl
run "probes_the_health_port_and_mounts_the_ledger_volume" {
  command = plan

  assert {
    condition     = one(one(one(azurerm_container_app.this.template).container).liveness_probe).path == "/live" && one(one(one(azurerm_container_app.this.template).container).readiness_probe).path == "/ready"
    error_message = "liveness and readiness must call /live and /ready"
  }

  assert {
    condition     = one(one(azurerm_container_app.this.template).volume).storage_type == "EmptyDir"
    error_message = "the ledger volume is ephemeral"
  }
}
```

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

- `run "probes_the_health_port_and_mounts_the_ledger_volume" {`: Starts the test step `probes the health port and mounts the ledger volume`.
- `command = plan`: `command = plan`.
- `assert {`: Starts an `assert` block.
- `condition     = one(one(one(azurerm_container_app.this.template).container).liveness_probe).path == "/live" &&`…: `condition` is the rule: `one(one(one(azurerm_container_app.this.template).container).liveness_probe).path == "/live" && one(one(one(azurerm_container_app.this.template).container).readiness_probe).path == "/ready"` must be true.
- `error_message = "liveness and readiness must call /live and /ready"`: `error_message` is shown when the rule fails: "liveness and readiness must call /live and /ready"
- `assert {`: Starts an `assert` block.
- `condition     = one(one(azurerm_container_app.this.template).volume).storage_type == "EmptyDir"`: `condition` is the rule: `one(one(azurerm_container_app.this.template).volume).storage_type == "EmptyDir"` must be true.
- `error_message = "the ledger volume is ephemeral"`: `error_message` is shown when the rule fails: "the ledger volume is ephemeral"
- Closing lines: `}` end the blocks opened above.

**Lines 76 to 86**

```hcl
run "refuses_a_variable_named_like_a_credential" {
  command = plan

  variables {
    env = {
      SB_CONNECTION_STRING = "x"
    }
  }

  expect_failures = [var.env]
}
```

- `run "refuses_a_variable_named_like_a_credential" {`: Starts the test step `refuses a variable named like a credential`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `env = {`: Sets the input variable `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value) to a group of named values that follows.
- `SB_CONNECTION_STRING = "x"`: Entry `SB_CONNECTION_STRING`: the text `"x"`.
- `expect_failures = [var.env]`: Expects the failure of [var.env].
- Closing lines: `}` end the blocks opened above.

**Lines 88 to 98**

```hcl
run "refuses_a_shared_access_key_variable_by_name" {
  command = plan

  variables {
    env = {
      SERVICEBUS_SHARED_ACCESS = "x"
    }
  }

  expect_failures = [var.env]
}
```

- `run "refuses_a_shared_access_key_variable_by_name" {`: Starts the test step `refuses a shared access key variable by name`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `env = {`: Sets the input variable `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value) to a group of named values that follows.
- `SERVICEBUS_SHARED_ACCESS = "x"`: Entry `SERVICEBUS_SHARED_ACCESS`: the text `"x"`.
- `expect_failures = [var.env]`: Expects the failure of [var.env].
- Closing lines: `}` end the blocks opened above.

**Lines 100 to 110**

```hcl
run "refuses_a_variable_valued_like_a_service_bus_connection_string" {
  command = plan

  variables {
    env = {
      BUS = "Endpoint=sb://mybus.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=abc"
    }
  }

  expect_failures = [var.env]
}
```

- `run "refuses_a_variable_valued_like_a_service_bus_connection_string" {`: Starts the test step `refuses a variable valued like a service bus connection string`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `env = {`: Sets the input variable `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value) to a group of named values that follows.
- `BUS = "Endpoint=sb://mybus.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessK`…: Entry `BUS`: the text `"Endpoint=sb://mybus.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=abc"`.
- `expect_failures = [var.env]`: Expects the failure of [var.env].
- Closing lines: `}` end the blocks opened above.

**Lines 112 to 120**

```hcl
run "refuses_the_latest_tag" {
  command = plan

  variables {
    image = "acrtest.azurecr.io/azure-service-bus-worker:latest"
  }

  expect_failures = [var.image]
}
```

- `run "refuses_the_latest_tag" {`: Starts the test step `refuses the latest tag`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `image = "acrtest.azurecr.io/azure-service-bus-worker:latest"`: Sets the input variable `image` (Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest) to the text `"acrtest.azurecr.io/azure-service-bus-worker:latest"`.
- `expect_failures = [var.image]`: Expects the failure of [var.image].
- Closing lines: `}` end the blocks opened above.

**Lines 122 to 130**

```hcl
run "refuses_zero_replicas" {
  command = plan

  variables {
    replicas = 0
  }

  expect_failures = [var.replicas]
}
```

- `run "refuses_zero_replicas" {`: Starts the test step `refuses zero replicas`.
- `command = plan`: `command = plan`.
- `variables {`: Starts a `variables` block.
- `replicas = 0`: Sets the input variable `replicas` (Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)) to the number `0`.
- `expect_failures = [var.replicas]`: Expects the failure of [var.replicas].
- Closing lines: `}` end the blocks opened above.

#### `infra/modules/worker_app/variables.tf`

93 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 4**

```hcl
variable "name" {
  description = "Container app name, for example ca-orders-worker."
  type        = string
}
```

- `variable "name" {`: Declares the input variable `name`.
- `description = "Container app name, for example ca-orders-worker."`: `description` documents it: "Container app name, for example ca-orders-worker."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 6 to 9**

```hcl
variable "environment_name" {
  description = "Container Apps environment name."
  type        = string
}
```

- `variable "environment_name" {`: Declares the input variable `environment_name`.
- `description = "Container Apps environment name."`: `description` documents it: "Container Apps environment name."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 11 to 14**

```hcl
variable "resource_group_name" {
  description = "Resource group that holds both."
  type        = string
}
```

- `variable "resource_group_name" {`: Declares the input variable `resource_group_name`.
- `description = "Resource group that holds both."`: `description` documents it: "Resource group that holds both."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 16 to 19**

```hcl
variable "location" {
  description = "Azure region."
  type        = string
}
```

- `variable "location" {`: Declares the input variable `location`.
- `description = "Azure region."`: `description` documents it: "Azure region."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 21 to 24**

```hcl
variable "log_analytics_workspace_id" {
  description = "Workspace that receives the console logs."
  type        = string
}
```

- `variable "log_analytics_workspace_id" {`: Declares the input variable `log_analytics_workspace_id`.
- `description = "Workspace that receives the console logs."`: `description` documents it: "Workspace that receives the console logs."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 26 to 34**

```hcl
variable "image" {
  description = "Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest."
  type        = string

  validation {
    condition     = !endswith(var.image, ":latest") && can(regex(":[^/]+$|@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must carry a version tag or a digest, and not be :latest."
  }
}
```

- `variable "image" {`: Declares the input variable `image`.
- `description = "Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version t`…: `description` documents it: "Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = !endswith(var.image, ":latest") && can(regex(":[^/]+$|@sha256:[0-9a-f]{64}$", var.image))`: `condition` is the rule: `!endswith(var.image, ":latest") && can(regex(":[^/]+$|@sha256:[0-9a-f]{64}$", var.image))` must be true. `endswith(text, suffix)` is true when the text ends with the suffix.
- `error_message = "image must carry a version tag or a digest, and not be :latest."`: `error_message` is shown when the rule fails: "image must carry a version tag or a digest, and not be :latest."
- Closing lines: `}` end the blocks opened above.

**Lines 36 to 40**

```hcl
variable "health_port" {
  description = "Port of the worker's health endpoint (/live and /ready); the platform's probes call it."
  type        = number
  default     = 8080
}
```

- `variable "health_port" {`: Declares the input variable `health_port`.
- `description = "Port of the worker's health endpoint (/live and /ready); the platform's probes call it."`: `description` documents it: "Port of the worker's health endpoint (/live and /ready); the platform's probes call it."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 8080`: `default` is used when the caller passes nothing: the number `8080`.
- Closing line: `}` ends the block opened above.

**Lines 42 to 46**

```hcl
variable "ledger_directory" {
  description = "Directory where the ephemeral volume is mounted; the worker's LEDGER_PATH points into it."
  type        = string
  default     = "/data"
}
```

- `variable "ledger_directory" {`: Declares the input variable `ledger_directory`.
- `description = "Directory where the ephemeral volume is mounted; the worker's LEDGER_PATH points into it."`: `description` documents it: "Directory where the ephemeral volume is mounted; the worker's LEDGER_PATH points into it."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "/data"`: `default` is used when the caller passes nothing: the text `"/data"`.
- Closing line: `}` ends the block opened above.

**Lines 48 to 51**

```hcl
variable "worker_identity_id" {
  description = "Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)."
  type        = string
}
```

- `variable "worker_identity_id" {`: Declares the input variable `worker_identity_id`.
- `description = "Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)."`: `description` documents it: "Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 53 to 56**

```hcl
variable "pull_identity_id" {
  description = "Resource id of the identity that only pulls the image (AcrPull on the registry)."
  type        = string
}
```

- `variable "pull_identity_id" {`: Declares the input variable `pull_identity_id`.
- `description = "Resource id of the identity that only pulls the image (AcrPull on the registry)."`: `description` documents it: "Resource id of the identity that only pulls the image (AcrPull on the registry)."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 58 to 61**

```hcl
variable "registry_server" {
  description = "Registry host, for example myregistry.azurecr.io."
  type        = string
}
```

- `variable "registry_server" {`: Declares the input variable `registry_server`.
- `description = "Registry host, for example myregistry.azurecr.io."`: `description` documents it: "Registry host, for example myregistry.azurecr.io."
- `type        = string`: `type` limits what is accepted: `string`: text.
- Closing line: `}` ends the block opened above.

**Lines 63 to 83**

```hcl
variable "env" {
  description = "Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value."
  type        = map(string)
  default     = {}

  validation {
    condition = !anytrue([
      for name in keys(var.env) :
      can(regex("(?i)(password|passwd|connection_?string|client_?secret|account_?key|sas_?token|api_?key|shared_?access)", name))
    ])
    error_message = "An environment variable name suggests a credential (password, connection string, client secret, account key, SAS token, API key). The app authenticates with its managed identity instead."
  }

  validation {
    condition = !anytrue([
      for value in values(var.env) :
      can(regex("(?i)(accountkey=|sharedaccesskey=|sharedaccesssignature=|[?&]sig=|password=|pwd=|-----BEGIN|endpoint=sb://)", value))
    ])
    error_message = "An environment variable value looks like a connection string, SAS token or private key."
  }
}
```

**New idea.** An **API** (application programming interface) is a way for one program to ask another to do something. A **REST** API does it with ordinary web requests: the program sends an HTTP request to an address and reads the answer, usually JSON.

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

- `variable "env" {`: Declares the input variable `env`.
- `description = "Plain environment variables: addresses and the client id of the identity. Credentials are refus`…: `description` documents it: "Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition = !anytrue([`: `condition` is the rule: `!anytrue([` must be true.
- `for name in keys(var.env) :`: Part of a `for` expression: `for name in keys(var.env) :`.
- `can(regex("(?i)(password|passwd|connection_?string|client_?secret|account_?key|sas_?token|api_?key|shared_?acc`…: Item: an expression (see the quote).
- `error_message = "An environment variable name suggests a credential (password, connection string, client secre`…: `error_message` is shown when the rule fails: "An environment variable name suggests a credential (password, connection string, client secret, account key, SAS token, API key). The app authenticates with its managed identity instead."
- `validation {`: Starts a rule the input value must satisfy.
- `condition = !anytrue([`: `condition` is the rule: `!anytrue([` must be true.
- `for value in values(var.env) :`: Part of a `for` expression: `for value in values(var.env) :`. `values(map)` lists a map's values.
- `can(regex("(?i)(accountkey=|sharedaccesskey=|sharedaccesssignature=|[?&]sig=|password=|pwd=|-----BEGIN|endpoin`…: Item: an expression (see the quote).
- `error_message = "An environment variable value looks like a connection string, SAS token or private key."`: `error_message` is shown when the rule fails: "An environment variable value looks like a connection string, SAS token or private key."
- Closing lines: `])`, `}` end the blocks opened above.

**Lines 85 to 94**

```hcl
variable "replicas" {
  description = "Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 1 && var.replicas <= 10
    error_message = "replicas must be between 1 and 10."
  }
}
```

- `variable "replicas" {`: Declares the input variable `replicas`.
- `description = "Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance check`…: `description` documents it: "Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 1`: `default` is used when the caller passes nothing: the number `1`.
- `validation {`: Starts a rule the input value must satisfy.
- `condition     = var.replicas >= 1 && var.replicas <= 10`: `condition` is the rule: `var.replicas >= 1 && var.replicas <= 10` must be true.
- `error_message = "replicas must be between 1 and 10."`: `error_message` is shown when the rule fails: "replicas must be between 1 and 10."
- Closing lines: `}` end the blocks opened above.

**Lines 96 to 100**

```hcl
variable "cpu" {
  description = "vCPU per replica."
  type        = number
  default     = 0.25
}
```

- `variable "cpu" {`: Declares the input variable `cpu`.
- `description = "vCPU per replica."`: `description` documents it: "vCPU per replica."
- `type        = number`: `type` limits what is accepted: `number`: a numeric value (whole or decimal).
- `default     = 0.25`: `default` is used when the caller passes nothing: the number `0.25`.
- Closing line: `}` ends the block opened above.

**Lines 102 to 106**

```hcl
variable "memory" {
  description = "Memory per replica; Container Apps pairs 0.25 vCPU with 0.5Gi."
  type        = string
  default     = "0.5Gi"
}
```

- `variable "memory" {`: Declares the input variable `memory`.
- `description = "Memory per replica; Container Apps pairs 0.25 vCPU with 0.5Gi."`: `description` documents it: "Memory per replica; Container Apps pairs 0.25 vCPU with 0.5Gi."
- `type        = string`: `type` limits what is accepted: `string`: text.
- `default     = "0.5Gi"`: `default` is used when the caller passes nothing: the text `"0.5Gi"`.
- Closing line: `}` ends the block opened above.

**Lines 108 to 112**

```hcl
variable "tags" {
  description = "Tags applied to both resources."
  type        = map(string)
  default     = {}
}
```

- `variable "tags" {`: Declares the input variable `tags`.
- `description = "Tags applied to both resources."`: `description` documents it: "Tags applied to both resources."
- `type        = map(string)`: `type` limits what is accepted: `map(string)`: a set of named texts (name to text).
- `default     = {}`: `default` is used when the caller passes nothing: `{}`.
- Closing line: `}` ends the block opened above.

#### `infra/modules/worker_app/versions.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }
}
```

- `terraform {`: Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: Lists the provider plug-ins needed.
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- Closing lines: `}` end the blocks opened above.

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
