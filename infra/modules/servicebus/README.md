# Module: servicebus

A **Standard** Service Bus namespace with Entra ID authentication only (`local_auth_enabled = false`: no SAS keys, no connection strings), TLS 1.2, the queues you describe, operational logs and metrics in a workspace, and an optional alert that fires when any dead-letter queue is not empty.

Standard is required for sessions. Queue settings default to the lesson's: a **30-second lock** and a **maximum delivery count of 10**. `requires_session` cannot be turned on for an existing queue, so the session queue (`orders-sessions`) is created as a second queue.

| Input | Meaning | Default |
|---|---|---|
| `name` | 6 to 50 characters, globally unique | required |
| `resource_group_name`, `location` | Placement | required |
| `queues` | Map of queue name to `lock_duration`, `max_delivery_count`, `requires_session`, `default_message_ttl` | required |
| `log_analytics_workspace_id` | Receives `OperationalLogs` and `AllMetrics` | required |
| `alert_email_addresses` | Recipients of the dead-letter alert; empty means no alert | `[]` |
| `tags` | Tags | `{}` |

| Output | Meaning |
|---|---|
| `id`, `name` | The namespace |
| `fully_qualified_namespace` | The programs' `SB_NAMESPACE` |
| `queue_ids` | Map of queue name to resource id (role assignment scopes) |
| `queue_names` | Names |

Test: `tests/servicebus.tftest.hcl` (Standard tier, no local auth, lesson queue settings, session queue, alert only with recipients, validations).
