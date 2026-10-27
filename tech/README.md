# Technology notes for azure-service-bus-worker

This folder teaches every technology the repository uses, starting from zero, through the repository's own files. You do not need to know any of them first. Each note says what the technology is, why this repository uses it, where it appears, how it works underneath, and then walks through this repository's own lines, quoting them and explaining each one. Code blocks in the walkthroughs are copied from the real files, and the output under each "Try it yourself" command was captured by running that command in this repository.

The repository is an order-processing worker for Azure Service Bus that is made to fail in three classic ways (duplicates from lock expiry, lost order, a poison message) and then fixed, with a simulated Service Bus so every failure also runs offline, and the Terraform that builds the Azure side of it.

Documentation formats (Markdown and Mermaid in the README and ARCHITECTURE files) have no note of their own: they hold prose and diagrams, and no code runs from them.

Every file follows the same nine headings: what it is, why this repository uses it, where it appears, how it works underneath, a walkthrough of this repository's own files, things to try, common mistakes, five questions with answers, and the official documentation.

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
