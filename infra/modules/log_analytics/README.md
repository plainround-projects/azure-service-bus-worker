# Module: log_analytics

A Log Analytics workspace where the Service Bus namespace's operational logs and metrics, and the worker's console logs land, so lock-lost errors and dead-letter events can be read with a query.

| Input | Meaning | Default |
|---|---|---|
| `name` | Workspace name | required |
| `resource_group_name`, `location` | Where it lives | required |
| `retention_in_days` | 30 to 730 | `30` |
| `tags` | Tags | `{}` |

| Output | Meaning |
|---|---|
| `id` | Resource id for diagnostic settings |
| `name` | Workspace name |
| `workspace_id` | Customer id for queries |

Test: `tests/log_analytics.tftest.hcl` (retention bounds).
