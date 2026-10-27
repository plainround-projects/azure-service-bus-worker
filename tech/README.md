# Technology notes for azure-service-bus-worker

This folder teaches every technology the repository uses, starting from zero, through the repository's own files. You do not need to know any of them first. Each note says what the technology is, why this repository uses it, where it appears, how it works underneath, and then walks through this repository's own lines, quoting them and explaining each one. Code blocks in the walkthroughs are copied from the real files, and the output under each "Try it yourself" command was captured by running that command in this repository.

The repository is an order-processing worker for Azure Service Bus that is made to fail in three classic ways (duplicates from lock expiry, lost order, a poison message) and then fixed, with a simulated Service Bus so every failure also runs offline, and the Terraform that builds the Azure side of it.

Documentation formats (Markdown and Mermaid in the README and ARCHITECTURE files) have no note of their own: they hold prose and diagrams, and no code runs from them.

Every file follows the same nine headings: what it is, why this repository uses it, where it appears, how it works underneath, a walkthrough of this repository's own files, things to try, common mistakes, five questions with answers, and the official documentation.

The walkthrough of each note has two parts. The first explains the key ideas with chosen quotes. The second, under the heading "Every line, in order", quotes every non-blank line of every code and configuration file that note is responsible for, in blocks with their line numbers, and explains each block. Ideas such as a process, a port, an environment variable, a transaction or a certificate are explained the first time a block needs them.

## The files

| File | Its role in this repository |
|---|---|
| [`python.md`](python.md) | The language of the worker, the producer, the replay tool and the simulation. |
| [`azure-servicebus.md`](azure-servicebus.md) | The Python client for Service Bus: senders, peek-lock receivers, sessions and lock renewal. |
| [`sqlite.md`](sqlite.md) | The small database the worker writes results to. |
| [`sql.md`](sql.md) | The schema, seed data, queries, migration and reset script. |
| [`pytest.md`](pytest.md) | Runs the tests and measures how much code they run. |
| [`json.md`](json.md) | The format of the command messages, the replay tool's repairs and the log lines. |
| [`pyproject-toml.md`](pyproject-toml.md) | The one configuration file of the Python project. |
| [`pip-uv-and-lock-files.md`](pip-uv-and-lock-files.md) | How the exact set of Python packages is installed and pinned. |
| [`git.md`](git.md) | Records the history and keeps local state out of it. |
| [`editorconfig.md`](editorconfig.md) | Keeps whitespace consistent across editors. |
| [`ruff.md`](ruff.md) | Checks and formats the Python code on every `make lint`. |
| [`mypy.md`](mypy.md) | Checks the type hints across the source and the tests. |
| [`import-linter.md`](import-linter.md) | Fails the build when a layer imports something it must not. |
| [`azure-identity.md`](azure-identity.md) | Gets Azure access tokens for the Service Bus client with no stored secret. |
| [`bash.md`](bash.md) | The scripts under `scripts/` that run the lesson against Azure. |
| [`shellcheck.md`](shellcheck.md) | Lints every script on `make lint`. |
| [`make.md`](make.md) | The one command per job: `make demos`, `make test`, `make lint`, `make up`. |
| [`docker.md`](docker.md) | Packages the worker as a small non-root image. |
| [`yaml.md`](yaml.md) | The format of the CI workflow and the checkov settings. |
| [`github-actions.md`](github-actions.md) | Runs the same checks on every push. |
| [`azure-cli.md`](azure-cli.md) | The commands the scripts use to sign in, read queue properties and build the image. |
| [`azure-managed-identity-rbac.md`](azure-managed-identity-rbac.md) | Who the worker is and what it may do on the queues. |
| [`azure-service-bus.md`](azure-service-bus.md) | The broker whose three classic failures the lesson causes on purpose. |
| [`azure-container-apps.md`](azure-container-apps.md) | Runs the worker image with the managed identity attached. |
| [`azure-container-registry.md`](azure-container-registry.md) | Stores the app image and lets the pull identity fetch it. |
| [`azure-monitor-log-analytics.md`](azure-monitor-log-analytics.md) | Where the namespace's logs go and what mails you when a dead letter appears. |
| [`azure-resources-and-budgets.md`](azure-resources-and-budgets.md) | The scope of the lesson and a spending alert. |
| [`terraform.md`](terraform.md) | Defines every Azure resource of the lesson as code. |
| [`terraform-providers.md`](terraform-providers.md) | The plugins that create Azure resources and random names. |
| [`tflint.md`](tflint.md) | Lints the Terraform on `make lint`. |
| [`checkov.md`](checkov.md) | Scans the Terraform, Dockerfile and workflow for security misconfigurations. |

## Reading order

1. [Python](python.md)
2. [pyproject.toml and TOML](pyproject-toml.md)
3. [pip, uv, virtual environments and lock files](pip-uv-and-lock-files.md)
4. [JSON](json.md)
5. [SQL](sql.md)
6. [SQLite](sqlite.md)
7. [Azure Service Bus](azure-service-bus.md)
8. [azure-servicebus (and azure-identity)](azure-servicebus.md)
9. [azure-identity (and azure-core)](azure-identity.md)
10. [pytest and coverage](pytest.md)
11. [ruff](ruff.md)
12. [mypy](mypy.md)
13. [import-linter](import-linter.md)
14. [.editorconfig](editorconfig.md)
15. [Git and .gitignore](git.md)
16. [Bash](bash.md)
17. [ShellCheck](shellcheck.md)
18. [GNU Make](make.md)
19. [Docker and the Dockerfile](docker.md)
20. [YAML](yaml.md)
21. [GitHub Actions](github-actions.md)
22. [Azure CLI](azure-cli.md)
23. [Resource groups, tags, providers and the budget](azure-resources-and-budgets.md)
24. [Managed identity and Azure RBAC](azure-managed-identity-rbac.md)
25. [Azure Container Registry](azure-container-registry.md)
26. [Azure Container Apps (the worker)](azure-container-apps.md)
27. [Log Analytics, diagnostic settings and the dead-letter alert](azure-monitor-log-analytics.md)
28. [Terraform](terraform.md)
29. [The azurerm and random providers](terraform-providers.md)
30. [TFLint](tflint.md)
31. [Checkov](checkov.md)

## If you have ten minutes

Read these three, in this order:

- [Azure Service Bus](azure-service-bus.md)
- [azure-servicebus (and azure-identity)](azure-servicebus.md)
- [SQLite](sqlite.md)

## Where every file is explained, line by line

Every code and configuration file of the repository is explained line by line in exactly one of the notes (the section "Every line, in order"). Files that are not listed here are documentation (Markdown), the license, generated lock files (the format is explained in the notes on lock files), or an example environment file that is described by its purpose only.

| File | Non-blank lines | Explained in |
|---|---|---|
| `.checkov.yaml` | 14 | [checkov.md](checkov.md) |
| `.dockerignore` | 19 | [docker.md](docker.md) |
| `.editorconfig` | 14 | [editorconfig.md](editorconfig.md) |
| `.github/workflows/ci.yml` | 41 | [github-actions.md](github-actions.md) |
| `.gitignore` | 26 | [git.md](git.md) |
| `.tflint.hcl` | 13 | [tflint.md](tflint.md) |
| `Dockerfile` | 26 | [docker.md](docker.md) |
| `Makefile` | 111 | [make.md](make.md) |
| `infra/environments/dev/backend.hcl.example` | 7 | [terraform.md](terraform.md) |
| `infra/environments/dev/main.tf` | 150 | [terraform.md](terraform.md) |
| `infra/environments/dev/outputs.tf` | 60 | [terraform.md](terraform.md) |
| `infra/environments/dev/providers.tf` | 12 | [terraform-providers.md](terraform-providers.md) |
| `infra/environments/dev/terraform.tfvars.example` | 23 | [terraform.md](terraform.md) |
| `infra/environments/dev/tests/dev.tftest.hcl` | 163 | [terraform.md](terraform.md) |
| `infra/environments/dev/variables.tf` | 125 | [terraform.md](terraform.md) |
| `infra/environments/dev/versions.tf` | 16 | [terraform-providers.md](terraform-providers.md) |
| `infra/modules/budget/main.tf` | 19 | [azure-resources-and-budgets.md](azure-resources-and-budgets.md) |
| `infra/modules/budget/outputs.tf` | 4 | [terraform.md](terraform.md) |
| `infra/modules/budget/tests/budget.tftest.hcl` | 29 | [terraform.md](terraform.md) |
| `infra/modules/budget/variables.tf` | 41 | [terraform.md](terraform.md) |
| `infra/modules/budget/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/main.tf` | 18 | [azure-container-registry.md](azure-container-registry.md) |
| `infra/modules/container_registry/outputs.tf` | 12 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/tests/container_registry.tftest.hcl` | 20 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/variables.tf` | 30 | [terraform.md](terraform.md) |
| `infra/modules/container_registry/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/main.tf` | 8 | [azure-monitor-log-analytics.md](azure-monitor-log-analytics.md) |
| `infra/modules/log_analytics/outputs.tf` | 12 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/tests/log_analytics.tftest.hcl` | 20 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/variables.tf` | 26 | [terraform.md](terraform.md) |
| `infra/modules/log_analytics/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/main.tf` | 9 | [azure-managed-identity-rbac.md](azure-managed-identity-rbac.md) |
| `infra/modules/role_assignments/outputs.tf` | 10 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/tests/role_assignments.tftest.hcl` | 87 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/variables.tf` | 31 | [terraform.md](terraform.md) |
| `infra/modules/role_assignments/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/main.tf` | 75 | [azure-service-bus.md](azure-service-bus.md) |
| `infra/modules/servicebus/outputs.tf` | 20 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/tests/servicebus.tftest.hcl` | 85 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/variables.tf` | 50 | [terraform.md](terraform.md) |
| `infra/modules/servicebus/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/main.tf` | 6 | [azure-managed-identity-rbac.md](azure-managed-identity-rbac.md) |
| `infra/modules/user_assigned_identity/outputs.tf` | 16 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/tests/user_assigned_identity.tftest.hcl` | 14 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/variables.tf` | 17 | [terraform.md](terraform.md) |
| `infra/modules/user_assigned_identity/versions.tf` | 9 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/main.tf` | 74 | [azure-container-apps.md](azure-container-apps.md) |
| `infra/modules/worker_app/outputs.tf` | 8 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/tests/worker_app.tftest.hcl` | 102 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/variables.tf` | 93 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/versions.tf` | 9 | [terraform.md](terraform.md) |
| `pyproject.toml` | 87 | [pyproject-toml.md](pyproject-toml.md) |
| `scripts/build-and-deploy.sh` | 27 | [bash.md](bash.md) |
| `scripts/docker-smoke.sh` | 20 | [bash.md](bash.md) |
| `scripts/env.sh` | 8 | [bash.md](bash.md) |
| `scripts/lib.sh` | 31 | [bash.md](bash.md) |
| `scripts/provision.sh` | 34 | [bash.md](bash.md) |
| `scripts/run-workers.sh` | 25 | [bash.md](bash.md) |
| `scripts/show-queues.sh` | 14 | [bash.md](bash.md) |
| `scripts/teardown.sh` | 13 | [bash.md](bash.md) |
| `sql/001_schema.sql` | 26 | [sql.md](sql.md) |
| `sql/002_seed.sql` | 4 | [sql.md](sql.md) |
| `sql/003_queries.sql` | 27 | [sql.md](sql.md) |
| `sql/migrations/001_processed_messages.sql` | 6 | [sql.md](sql.md) |
| `sql/reset.sql` | 4 | [sql.md](sql.md) |
| `src/order_worker/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/application/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/application/check_ledger.py` | 55 | [python.md](python.md) |
| `src/order_worker/application/handle_delivery.py` | 99 | [python.md](python.md) |
| `src/order_worker/application/ports.py` | 95 | [python.md](python.md) |
| `src/order_worker/application/produce_orders.py` | 23 | [python.md](python.md) |
| `src/order_worker/application/replay_dead_letters.py` | 85 | [python.md](python.md) |
| `src/order_worker/application/run_worker.py` | 83 | [python.md](python.md) |
| `src/order_worker/domain/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/domain/commands.py` | 69 | [python.md](python.md) |
| `src/order_worker/domain/errors.py` | 19 | [python.md](python.md) |
| `src/order_worker/domain/ordering.py` | 4 | [python.md](python.md) |
| `src/order_worker/domain/processing.py` | 29 | [python.md](python.md) |
| `src/order_worker/domain/repair.py` | 19 | [python.md](python.md) |
| `src/order_worker/infrastructure/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/infrastructure/clock.py` | 10 | [python.md](python.md) |
| `src/order_worker/infrastructure/health_server.py` | 53 | [python.md](python.md) |
| `src/order_worker/infrastructure/logging.py` | 29 | [python.md](python.md) |
| `src/order_worker/infrastructure/scenarios.py` | 159 | [python.md](python.md) |
| `src/order_worker/infrastructure/servicebus.py` | 149 | [azure-servicebus.md](azure-servicebus.md) |
| `src/order_worker/infrastructure/settings.py` | 74 | [python.md](python.md) |
| `src/order_worker/infrastructure/shutdown.py` | 23 | [python.md](python.md) |
| `src/order_worker/infrastructure/simulation.py` | 246 | [python.md](python.md) |
| `src/order_worker/infrastructure/sqlite_ledger.py` | 83 | [sqlite.md](sqlite.md) |
| `src/order_worker/infrastructure/wiring.py` | 11 | [python.md](python.md) |
| `src/order_worker/interfaces/__init__.py` | 1 | [python.md](python.md) |
| `src/order_worker/interfaces/check_cli.py` | 32 | [python.md](python.md) |
| `src/order_worker/interfaces/common.py` | 22 | [python.md](python.md) |
| `src/order_worker/interfaces/dlq_cli.py` | 44 | [python.md](python.md) |
| `src/order_worker/interfaces/produce_cli.py` | 25 | [python.md](python.md) |
| `src/order_worker/interfaces/simulate_cli.py` | 122 | [python.md](python.md) |
| `src/order_worker/interfaces/worker_cli.py` | 72 | [python.md](python.md) |
| `tests/conftest.py` | 10 | [pytest.md](pytest.md) |
| `tests/e2e/test_lesson_scenarios.py` | 125 | [pytest.md](pytest.md) |
| `tests/integration/test_azure_live.py` | 29 | [pytest.md](pytest.md) |
| `tests/integration/test_sqlite_ledger.py` | 121 | [pytest.md](pytest.md) |
| `tests/unit/application/fakes.py` | 101 | [pytest.md](pytest.md) |
| `tests/unit/application/test_handle_delivery.py` | 95 | [pytest.md](pytest.md) |
| `tests/unit/application/test_produce_replay_and_check.py` | 106 | [pytest.md](pytest.md) |
| `tests/unit/application/test_run_worker.py` | 84 | [pytest.md](pytest.md) |
| `tests/unit/domain/test_commands_ordering_and_repair.py` | 77 | [pytest.md](pytest.md) |
| `tests/unit/infrastructure/test_servicebus_adapter.py` | 184 | [pytest.md](pytest.md) |
| `tests/unit/infrastructure/test_settings_logging_clock_shutdown.py` | 119 | [pytest.md](pytest.md) |
| `tests/unit/infrastructure/test_simulation.py` | 129 | [pytest.md](pytest.md) |
| `tests/unit/interfaces/test_clis.py` | 106 | [pytest.md](pytest.md) |
