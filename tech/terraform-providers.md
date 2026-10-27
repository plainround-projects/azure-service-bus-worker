# The azurerm and random providers

*The plugins that create Azure resources and random names. Pinned here: azurerm 4.81.0, random 3.9.1.*

## What it is

A Terraform **provider** is a plugin that knows how to talk to one service's API. `azurerm` creates Azure resources. `random` makes random values, such as the five characters that make a name unique. Providers are published in the Terraform Registry and downloaded by `terraform init`.

## Why this repository uses it

Terraform itself knows nothing about Azure. The `azurerm` provider supplies the resource types (`azurerm_key_vault`) and turns them into Azure API calls; `random` supplies the short suffix that makes globally unique names.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/environments/dev/versions.tf` | Names the providers and their version rules. |
| `infra/environments/dev/providers.tf` | Configures azurerm. |
| `infra/environments/dev/.terraform.lock.hcl` | The exact versions and hashes. |
| `infra/modules/*/versions.tf` | Each module states the provider it needs. |

## How it works underneath

The `required_providers` block names each provider and a version rule: `version = "~> 4.81"` means 4.81 or any newer 4.x, never 5. The first `terraform init` picks the newest match and `.terraform.lock.hcl` records the exact version (4.81.0) and **hashes** of its files for each operating system, so another machine installs the same bytes.

A `provider "azurerm" { ... }` block configures the plugin: which subscription to use, and `features {}`, which the azurerm provider requires. When the plugin configures itself it signs in (using `az login` or environment variables). That is why a real `terraform plan` needs credentials, and why these repositories test with `mock_provider`.

`resource_provider_registrations = "none"` stops the plugin from registering Azure resource providers on its own; the provisioning script does that once.

## Walkthrough of this repository's use

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Local state keeps the practice run self-contained. For a shared environment copy backend.hcl.example to
  # backend.hcl, uncomment the block below and run `terraform init -backend-config=backend.hcl`.
  # backend "azurerm" {}
}
```

`required_version = ">= 1.9"` refuses older Terraform. `~> 4.81` allows 4.81 and newer 4.x. The commented `backend "azurerm" {}` shows where remote state would go.

```hcl
provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id

  # scripts/provision.sh registers the resource providers this slice needs, so the plan never changes
  # subscription-wide settings on its own.
  resource_provider_registrations = "none"

  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
```

`subscription_id` and `tenant_id` come from variables, not from files committed to Git. `resource_provider_registrations = "none"` stops the plugin from registering Azure resource providers by itself (the provisioning script does it once). `features { resource_group { prevent_deletion_if_contains_resources = false } }` states a behavior azurerm requires you to choose: `terraform destroy` may remove a resource group together with what is in it.

```hcl
provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "4.81.0"
  constraints = "~> 4.81"
  hashes = [
    "h1:VVNpxIBEc/i8lpiYMG4dcowT+ilEnsVYfrBVAKMajes=",
    "h1:XhToZua4gtih1Kv8RdStcfND83G4Tmb6GZFT4jEUhDU=",
    "h1:olVprUWhmFTARlydw/r7VIx4fata2gy3zsAWfPGRrhg=",
    "h1:uA4c+rHQWo793Bi8xMC+YlC6kVN06oC+bd0WNKn18cE=",
    "zh:0732e7b74264ddfa2b90ba69d01c283d3cbae9f72ed3e506c6ac92529fed7fd3",
    "zh:12afb524e232fe4e3d6161927724af5dfa4831d71edd9c174917ca9b7377bfae",
    "zh:169d619ae202c4145e02fb706fb7c3679445ab3e3ff722edbf89597517a8c92e",
    "zh:6beb95a3ef2f2d9c76abaa48e5450e90686a3fb6a47f1cb0ff7c5e94b6960151",
    "zh:705e075fb5ffc4bf66fd7cbabf1a65007a41621e80030a2c158a4c83b6046216",
    "zh:78d5eefdd9e494defcb3c68d282b8f96630502cac21d1ea161f53cfe9bb483b3",
    "zh:79a8d17fefe647040fcb9ee8821a4f09f395427c4fd49493489b9a93a9a1038e",
    "zh:8cc3f900b3774c0ae37ae42365c4579a199cf9e5edf88e476fdf5ab1048f84ea",
    "zh:dec373b9390fa95e257291acd018ed65a7d512b428645d35e22cdbe8b245a08b",
    "zh:e60f1e9fb45df6defade2855ed6e68547409ea75d30655c556adb0c08579749b",
    "zh:f901d12ec82f3f8b5880a27b5cbcd7bd0d97e60c9367a2d7ed82fdd1157b39ff",
    "zh:facf68ea5bf0f2b8ba720e7fba5f86492e1d4c591100460bb91c3f79f391f4b6",
  ]
}
```

The lock file records the exact version and (further down) hashes for four platforms, which `terraform providers lock -platform=...` added so CI on Linux accepts the same lock.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/environments/dev/providers.tf`

12 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 14**

```hcl
provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id

  # scripts/provision.sh registers the resource providers this slice needs, so the plan never changes
  # subscription-wide settings on its own.
  resource_provider_registrations = "none"

  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
```

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** A **GUID** (or UUID) is a 128-bit identifier written as 32 hexadecimal digits in groups, such as `00000000-0000-0000-0000-000000000000`. Azure uses them for subscriptions, tenants and identities. The all-zero value in examples is a placeholder, not a real id.

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

- `provider "azurerm" {`: A `provider` block configures a plug-in that knows how to talk to one service (here `azurerm`, for Azure). It holds settings that apply to every resource of that provider. Configures the `azurerm` provider.
- `subscription_id = var.subscription_id`: `subscription_id`: The id of the Azure subscription (the billing container) to work in. Here: the input variable `subscription_id` (Subscription GUID (`az account show --query id`)).
- `tenant_id       = var.tenant_id`: `tenant_id`: The id of the Microsoft Entra ID tenant (the organization's identity directory) that owns the identities and decides access. Here: the input variable `tenant_id` (Entra tenant GUID (`az account show --query tenantId`)).
- `# scripts/provision.sh registers the resource providers this slice needs, so the plan never changes`: A line starting with `#` (or `//`) is a **comment**: Terraform ignores it; it is there for the reader. Comment for the reader: scripts/provision.sh registers the resource providers this slice needs, so the plan never changes
- `# subscription-wide settings on its own.`: Comment for the reader: subscription-wide settings on its own.
- `resource_provider_registrations = "none"`: `resource_provider_registrations`: Which Azure resource providers (the services behind resource types) Terraform registers on its own. `none` means it registers nothing, and the script does it once. Here: the text `"none"`.
- `features {`: Starts the nested `features` block: Provider-wide behavior switches (required even when empty).
- `resource_group {`: Starts the nested `resource_group` block: Behavior of the provider for resource groups.
- `prevent_deletion_if_contains_resources = false`: `prevent_deletion_if_contains_resources`: Whether Terraform refuses to delete a resource group that still contains resources it does not know about. Here: `false`.
- Closing lines: `}` end the blocks opened above.

#### `infra/environments/dev/versions.tf`

16 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 18**

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Local state keeps the practice run self-contained. For a shared environment copy backend.hcl.example to
  # backend.hcl, uncomment the block below and run `terraform init -backend-config=backend.hcl`.
  # backend "azurerm" {}
}
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

- `terraform {`: The `terraform` block sets rules for Terraform itself: which version may run this code, which provider plug-ins it needs and where to find them, and where to keep state. Starts the settings for Terraform itself.
- `required_version = ">= 1.9"`: `required_version`: Which Terraform versions may run this code. `>= 1.9` means 1.9 or newer. Here: the text `">= 1.9"`.
- `required_providers {`: `required_providers` lists the provider plug-ins this code needs, each with `source` (where to download it from) and `version` (which releases are allowed). `~> 4.81` means "4.81 or newer, but below 5.0".
- `azurerm = {`: Names the provider `azurerm`; its settings follow.
- `source  = "hashicorp/azurerm"`: Entry `source`: the text `"hashicorp/azurerm"`.
- `version = "~> 4.81"`: Entry `version`: the text `"~> 4.81"`.
- `random = {`: Names the provider `random`; its settings follow.
- `source  = "hashicorp/random"`: Entry `source`: the text `"hashicorp/random"`.
- `version = "~> 3.7"`: Entry `version`: the text `"~> 3.7"`.
- `# Local state keeps the practice run self-contained. For a shared environment copy backend.hcl.example to`: Comment for the reader: Local state keeps the practice run self-contained. For a shared environment copy backend.hcl.example to
- `# backend.hcl, uncomment the block below and run `terraform init -backend-config=backend.hcl`.`: Comment for the reader: backend.hcl, uncomment the block below and run `terraform init -backend-config=backend.hcl`.
- `# backend "azurerm" {}`: Comment for the reader: backend "azurerm" {}
- Closing lines: `}` end the blocks opened above.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/environments/dev/main.tf` | 70, 80 to 81, 89 to 90, 98 to 99, 107 to 108, 123 to 124, 140 to 141 | [terraform.md](terraform.md) |
| `infra/environments/dev/tests/dev.tftest.hcl` | 1, 4 to 5, 10, 15, 21, 26, 34, 41, 48, 57, 191, 196 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/main.tf` | 1, 18, 22, 34 to 36, 48, 67, 72, 88 | [azure-service-bus.md](azure-service-bus.md) |
| `infra/modules/servicebus/tests/servicebus.tftest.hcl` | 1, 18, 23, 32, 37, 46, 55, 64, 77 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/tests/worker_app.tftest.hcl` | 1, 24, 29, 34, 43, 52, 57, 66, 71 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/outputs.tf` | 3, 8, 13, 18, 23 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/outputs.tf` | 3, 8, 13, 18 | [terraform.md](terraform.md) |
| `.tflint.hcl` | 1, 11, 14 | [tflint.md](tflint.md) |
| `infra/modules/budget/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/outputs.tf` | 3, 8, 13 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/outputs.tf` | 3, 8, 13 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/tests/role_assignments.tftest.hcl` | 1, 17, 22 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/main.tf` | 1, 9, 12 | [azure-container-apps.md](azure-container-apps.md) |
| `infra/modules/worker_app/versions.tf` | 4 to 6 | [terraform.md](terraform.md) |
| `.gitignore` | 17, 28 | [git.md](git.md) |
| `infra/modules/budget/tests/budget.tftest.hcl` | 1, 15 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/tests/container_registry.tftest.hcl` | 1, 13 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/tests/log_analytics.tftest.hcl` | 1, 13 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/tests/user_assigned_identity.tftest.hcl` | 1, 14 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/outputs.tf` | 3, 8 | [terraform.md](terraform.md) |
| `Makefile` | 104 | [make.md](make.md) |
| `infra/environments/dev/outputs.tf` | 3 | [terraform.md](terraform.md) |
| `infra/modules/budget/main.tf` | 1 | [azure-resources-and-budgets.md](azure-resources-and-budgets.md) |
| `infra/modules/budget/outputs.tf` | 3 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/main.tf` | 1 | [azure-container-registry.md](azure-container-registry.md) |
| `infra/modules/log_analytics/main.tf` | 1 | [azure-monitor-log-analytics.md](azure-monitor-log-analytics.md) |
| `infra/modules/role_assignments/main.tf` | 1 | [azure-managed-identity-rbac.md](azure-managed-identity-rbac.md) |
| `infra/modules/role_assignments/outputs.tf` | 4 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/main.tf` | 1 | [azure-managed-identity-rbac.md](azure-managed-identity-rbac.md) |

## Try it yourself

See the locked versions.

```bash
grep -A2 'provider "registry' infra/environments/dev/.terraform.lock.hcl | grep -E 'provider|version'
```

You should see something like this:

```text
provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "4.81.0"
provider "registry.terraform.io/hashicorp/random" {
  version     = "3.9.1"
```

List the providers the configuration needs.

```bash
cd infra/environments/dev && terraform providers 2>&1 | head -12
```

You should see something like this:

```text
Providers required by configuration:
.
├── provider[registry.terraform.io/hashicorp/random] ~> 3.7
├── provider[registry.terraform.io/hashicorp/azurerm] ~> 4.81
├── test.tests.dev
├── module.pull_identity
│   └── provider[registry.terraform.io/hashicorp/azurerm] ~> 4.81
├── module.log_analytics
│   └── provider[registry.terraform.io/hashicorp/azurerm] ~> 4.81
├── module.registry
│   └── provider[registry.terraform.io/hashicorp/azurerm] ~> 4.81
```

Count the recorded hashes.

```bash
grep -c 'h1:\|zh:' infra/environments/dev/.terraform.lock.hcl
```

You should see something like this:

```text
33
```

## Mistakes people make

- Not committing the lock file, so teammates get different provider versions.
- Using `>= 4.0` with no upper bound; a new major version can break the configuration.
- Locking hashes for only your own platform; CI on Linux then fails. The lock files here cover four platforms.
- Forgetting `features {}` in the azurerm provider.
- Putting credentials in the provider block. Authentication comes from `az login`.

## Check yourself

1. **What does a provider do?**
   Answer: Translates resources in the files into calls to one service's API.

2. **What does `~> 4.81` allow?**
   Answer: Versions 4.81 and above within 4.x.

3. **What does the lock file record?**
   Answer: The exact provider version and hashes of its files.

4. **Why does a real `plan` need credentials?**
   Answer: The azurerm plugin signs in when it configures itself.

5. **What is the `random` provider used for here?**
   Answer: To make a short suffix so globally unique names do not collide.

## Further reading

- azurerm provider 4.x: https://registry.terraform.io/providers/hashicorp/azurerm/4.81.0/docs
- random provider 3.9: https://registry.terraform.io/providers/hashicorp/random/3.9.1/docs
- Dependency lock file: https://developer.hashicorp.com/terraform/language/files/dependency-lock
