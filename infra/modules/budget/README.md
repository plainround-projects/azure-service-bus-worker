# Module: budget

A monthly budget on the subscription with an email alert at 80 percent and 100 percent of actual spend (a safety net: a Standard namespace bills by the hour whether or not a message is sent). A budget is subscription-scoped, so deleting the resource group does not remove it: `terraform destroy` or `scripts/teardown.sh` does.

| Input | Meaning | Default |
|---|---|---|
| `name` | Budget name | required |
| `subscription_id` | GUID | required |
| `amount` | Monthly amount | required |
| `start_date` | First of a month, midnight UTC | required |
| `contact_emails` | Recipients | required |
| `thresholds_percent` | Alert levels | `[80, 100]` |

Test: `tests/budget.tftest.hcl` (two notifications, first-of-month rule, recipients required).
