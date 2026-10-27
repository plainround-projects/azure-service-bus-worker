# Module: worker_app

A Container Apps environment (logging to the workspace) and one container app that runs the order worker as a user-assigned identity.

- **No ingress.** The worker pulls from the queue; nothing connects to it. The platform's probes reach only the health port: `/live` (the receive loop made progress recently) and `/ready` (the ledger answers).
- **Two identities, two jobs.** `worker_identity_id` is what the code uses (named by `AZURE_CLIENT_ID`) and holds Data Receiver on its queue; `pull_identity_id` only pulls the image (AcrPull).
- **No secrets by construction.** The module has no `secret` block. `env` rejects names such as `password`, `connection_string`, `account_key` and values such as `AccountKey=`, `SharedAccessKey=`, `sig=` or a private key header, so a Service Bus connection string cannot be passed in.
- **No `:latest`.** `image` must carry a version tag or a digest.
- **Fixed replicas, ephemeral ledger.** `replicas` defaults to 1; the SQLite ledger sits on an `EmptyDir` volume and is lost when the replica is replaced.

| Input | Meaning | Default |
|---|---|---|
| `name`, `environment_name`, `resource_group_name`, `location` | Placement | required |
| `log_analytics_workspace_id` | Console logs | required |
| `image` | Versioned image | required |
| `worker_identity_id`, `pull_identity_id`, `registry_server` | Identities and registry | required |
| `env` | Plain variables | `{}` |
| `health_port` | Probe port | `8080` |
| `ledger_directory` | Mount path of the ledger volume | `/data` |
| `replicas` | 1 to 10 | `1` |
| `cpu`, `memory` | Per replica | `0.25`, `0.5Gi` |
| `tags` | Tags | `{}` |

| Output | Meaning |
|---|---|
| `name` | App name |
| `environment_id` | Environment id |

Test: `tests/worker_app.tftest.hcl` (no secret blocks, no ingress, probes, volume, credential-shaped variables and `:latest` refused).
