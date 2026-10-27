# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-27

### Added

- `tech/`: 31 technology notes (language, libraries, tools, services, file formats) with an index, a reading order and a ten-minute shortlist; every code quote is copied from the repository and every command's output was captured by running it.
- A layered Python package (`domain`, `application`, `infrastructure`, `interfaces`) with the worker, the producer, the dead-letter replay tool, the ledger checker and an offline simulation program.
- Service Bus adapters that authenticate only with `DefaultAzureCredential`, session receivers, automatic lock renewal, batching sender, graceful shutdown, JSON logging and an HTTP health endpoint.
- A simulated Service Bus (peek-lock, lock expiry, delivery counts, sessions, dead-lettering) and deterministic scenarios for the lesson's three failures.
- SQL scripts: schema, seed, the lesson's queries, the idempotency migration and a reset script.
- Terraform modules (`log_analytics`, `user_assigned_identity`, `servicebus`, `role_assignments`, `container_registry`, `worker_app`, `budget`) and the `dev` environment, each module with a README and `terraform test` tests against a mocked provider.
- The lesson's runbook as scripts, `docs/RUNBOOK.md` with the signal, cause and fix for each failure, decision records, a multi-stage non-root Dockerfile, hash-pinned lock files, import-linter, ruff, mypy, tflint and checkov configuration, and a CI workflow.
