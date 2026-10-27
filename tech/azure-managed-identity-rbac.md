# Managed identity and Azure RBAC

*Who the worker is and what it may do on the queues. Pinned here: Azure RBAC built-in roles; user-assigned managed identity.*

## What it is

A **managed identity** is an identity that Azure creates and manages for a resource, so the resource can prove who it is to other Azure services without any stored password. **Azure RBAC** (role-based access control) decides what an identity may do: a **role assignment** gives a **principal** (an identity) a **role** (a named set of permissions) at a **scope** (the resource it applies to).

## Why this repository uses it

The lesson gives the worker only Azure Service Bus Data Receiver on the queue and the producer only Data Sender, never the owner role.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/user_assigned_identity/` | Creates an identity. |
| `infra/modules/role_assignments/` | Creates role assignments and refuses wide scopes and the owner role. |
| `infra/environments/dev/main.tf` | Decides who gets which role on which queue. |
| `src/order_worker/infrastructure/wiring.py` | Uses the identity through `DefaultAzureCredential`. |

## How it works underneath

There are two kinds. A *system-assigned* identity belongs to one resource and is deleted with it. A *user-assigned* identity is its own resource that you can attach to several resources and keep when you replace one. Each identity has a **client id** (the app's name, safe to put in configuration) and a **principal id** or *object id* (what role assignments use).

Inside an Azure resource, code asks the **instance metadata service** at a local address for a token for the identity; Azure signs one and the resource sends it to the service it wants to call. The service looks at the token's principal and at the role assignments that apply to the resource being touched. A role assigned at a larger scope (a resource group) also applies to everything inside it, which is why the narrowest scope is chosen.

Role assignments take minutes to spread, so a call made right after a grant can fail with 403.

## Walkthrough of this repository's use

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

A `for` expression creates one assignment per queue: the worker identity gets `Azure Service Bus Data Receiver` on `orders` and on `orders-sessions`, each scoped to that queue's resource id. The worker can receive, complete, abandon and dead-letter, but it cannot send.

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
```

The operator (the person running the lesson) gets Data Sender and Data Receiver on each queue so the producer, a local worker and the replay tool work from a laptop. `merge([ for ... ]...)` builds one map per queue and merges them; the `...` after the list spreads it into arguments. The `if var.operator_object_id != null` leaves the map empty when no operator is named.

```hcl
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

Every scope must be a resource, never a subscription or resource group.

```hcl
    condition     = !anytrue([for assignment in var.assignments : contains(["Owner", "Contributor", "User Access Administrator", "Azure Service Bus Data Owner"], assignment.role)])
    error_message = "Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner are too wide; this project assigns the Data Sender and Data Receiver roles on single queues."
```

The roles Owner, Contributor, User Access Administrator and `Azure Service Bus Data Owner` (the namespace-wide data role) are refused at plan time.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/role_assignments/main.tf`

9 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 11**

```hcl
resource "azurerm_role_assignment" "this" {
  for_each = var.assignments

  principal_id         = each.value.principal_id
  principal_type       = each.value.principal_type
  role_definition_name = each.value.role
  scope                = each.value.scope

  # A service principal created seconds ago may not have replicated yet; the principal type avoids the lookup.
  skip_service_principal_aad_check = each.value.principal_type == "ServicePrincipal"
}
```

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

**New idea.** **Azure role-based access control (RBAC)** decides who may do what. A *role* is a named bundle of permissions (for example "Key Vault Secrets User" may read secrets), a *scope* is where the grant applies (one resource, a resource group, a whole subscription), and a *role assignment* connects an identity, a role and a scope. The smaller the scope, the less a leaked identity can do.

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

- `resource "azurerm_role_assignment" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_role_assignment.this`. A **role assignment** grants one identity (the `principal_id`) one role (what it may do) at one scope (where it may do it). Roles are the permission system of Azure (RBAC).
- `for_each = var.assignments`: `for_each` makes one copy of the resource (or module) for each entry of a map or set. Inside, `each.key` is the entry's key and `each.value` its value. Each copy is tracked under its key, so adding or removing one entry touches only that copy. `for_each` is set to the input variable `assignments`.
- `principal_id         = each.value.principal_id`: `principal_id`: The object id of the identity that receives the role. Here: `each.value`, the value of the entry being repeated.
- `principal_type       = each.value.principal_type`: `principal_type`: Whether the principal is a `User`, `ServicePrincipal` or `Group`. Saying it avoids a lookup that can fail right after the identity is created. Here: `each.value`, the value of the entry being repeated.
- `role_definition_name = each.value.role`: `role_definition_name`: The name of the role (a named bundle of permissions) being granted. Here: `each.value`, the value of the entry being repeated.
- `scope                = each.value.scope`: `scope`: The resource (or group of resources) at which the role applies. A role at a narrow scope grants less. Here: `each.value`, the value of the entry being repeated.
- `# A service principal created seconds ago may not have replicated yet; the principal type avoids the lookup.`: A line starting with `#` (or `//`) is a **comment**: Terraform ignores it; it is there for the reader. Comment for the reader: A service principal created seconds ago may not have replicated yet; the principal type avoids the lookup.
- `skip_service_principal_aad_check = each.value.principal_type == "ServicePrincipal"`: `skip_service_principal_aad_check`: Skips a directory lookup that can fail for a brand-new identity that has not finished replicating. Here: `each.value`, the value of the entry being repeated.
- Closing line: `}` ends the block opened above.

#### `infra/modules/user_assigned_identity/main.tf`

6 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 6**

```hcl
resource "azurerm_user_assigned_identity" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_user_assigned_identity" "this" {`: Declares the resource `azurerm_user_assigned_identity.this`. A **user-assigned managed identity** is an identity in Microsoft Entra ID that Azure creates and manages, with no password. A workload runs *as* it and asks for tokens; roles are then granted to it. It lives independently of any one resource.
- `name                = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Identity name, for example id-orders-worker).
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the identity).
- `location            = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the identity).
- Closing line: `}` ends the block opened above.

## Try it yourself

Run the module's tests, including the refused owner role.

```bash
cd infra/modules/role_assignments && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -4
```

You should see something like this:

```text
tests/role_assignments.tftest.hcl... tearing down
tests/role_assignments.tftest.hcl... pass

Success! 6 passed, 0 failed.
```

Find the two data roles in the composition.

```bash
grep -n 'Azure Service Bus Data' infra/environments/dev/main.tf
```

You should see something like this:

```text
38:      role         = "Azure Service Bus Data Receiver"
56:        role           = "Azure Service Bus Data Sender"
62:        role           = "Azure Service Bus Data Receiver"
```

## Mistakes people make

- Using the client id where the principal id is needed (`principal does not exist`).
- Assigning a role at the resource group or subscription when one resource is enough. The role module here refuses those scopes.
- Granting Owner or Contributor to an app. Data roles such as `Key Vault Secrets User` are narrower.
- Expecting Owner to read data. Management roles do not include data permissions.
- Reading a missing role as instant: wait a few minutes before deciding it is broken.

## Check yourself

1. **What is the difference between client id and principal id?**
   Answer: The client id names the application; the principal (object) id is what role assignments use.

2. **What are the three parts of a role assignment?**
   Answer: A principal, a role and a scope.

3. **Why choose the narrowest scope?**
   Answer: A role at a larger scope also applies to everything inside it.

4. **User-assigned or system-assigned: which survives replacing the app?**
   Answer: User-assigned, because it is its own resource.

5. **Why can a call fail right after a role is granted?**
   Answer: Role assignments take time to propagate.

## Further reading

- Managed identities: https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/overview
- Azure RBAC: https://learn.microsoft.com/en-us/azure/role-based-access-control/overview
- Built-in roles: https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
