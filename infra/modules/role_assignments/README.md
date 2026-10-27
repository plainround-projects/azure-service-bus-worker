# Module: role_assignments

Creates role assignments from a map and refuses the shapes that break least privilege:

- a scope that is a subscription or a resource group (only a resource or sub-resource is accepted);
- the roles Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner (the namespace-wide owner role).

Newly created service principals are assigned with their principal type and without the directory lookup, which avoids the "principal does not exist" delay the lesson warns about.

```hcl
module "role_assignments" {
  source = "../../modules/role_assignments"

  assignments = {
    worker_receives_orders = {
      principal_id = module.worker_identity.principal_id
      role         = "Azure Service Bus Data Receiver"
      scope        = module.servicebus.queue_ids["orders"]
    }
  }
}
```

| Output | Meaning |
|---|---|
| `assignments` | Map of key to `{ principal_id, role, scope }` |

Test: `tests/role_assignments.tftest.hcl` (accepts a queue scope, refuses resource group, subscription and wide roles).
