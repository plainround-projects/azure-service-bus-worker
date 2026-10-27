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
