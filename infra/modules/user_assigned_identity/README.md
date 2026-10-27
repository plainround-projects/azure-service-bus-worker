# Module: user_assigned_identity

A user-assigned managed identity. It is a separate resource from the app, so it survives replacing the app and its role assignments can exist before the app does. It holds no roles by itself; the `role_assignments` module grants them.

| Input | Meaning |
|---|---|
| `name`, `resource_group_name`, `location`, `tags` | Where and what |

| Output | Meaning |
|---|---|
| `id` | Resource id, for `identity_ids` |
| `principal_id` | Object id, for role assignments |
| `client_id` | AZURE_CLIENT_ID for the app; an address of the identity, not a secret |
| `name` | Identity name |
