# azure-service-bus-worker

An order-processing worker for Azure Service Bus that is made to fail in the three ways consumers usually fail, and then fixed: processing that outlasts the message lock (duplicates), commands for one customer handled out of order (sessions), and a message that can never succeed (the dead-letter queue, with a replay tool). The worker authenticates with a managed identity and holds one role, Data Receiver. The infrastructure is Terraform; the app is layered, typed Python; every failure also runs offline on a simulated broker, so the lesson can be rehearsed without a subscription.

**Lesson realized:** `/prep/azure/project-service-bus-worker` (`data-structure-explainer/src/content/tracks/azure/12-project-service-bus-worker.md` in the Plainround app), "The Service Bus worker you build" (Azure track, project 2). The lesson plans **9 hours**.
**Author:** Sumit Srivastava. **License:** MIT.

Nothing here has been deployed: the Azure subscription does not exist yet. Everything that can be checked without one has been (see [What was verified](#what-was-verified-without-a-subscription)); the rest is a list of commands in `scripts/` that you run once the subscription exists.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="The producer order-produce sends commands to the queues orders and orders-sessions; the order worker takes them under a 30 second peek-lock, writes the SQLite ledger and then completes; poison and exhausted messages go to the dead letters, and order-dlq replays them." src="docs/diagrams/architecture.svg">
</picture>

Notice that the ledger is written before the complete, and that the two amber edges, an expired lock and a poison message, are the two failures the demos drill.

## How one run flows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/flow-dark.svg">
  <img alt="One command is sent, taken under a peek-lock, validated, written to the ledger and completed; the amber rows show poison, an expired lock and ten deliveries without a complete, and the replay ends at 1000|10000.0." src="docs/diagrams/flow.svg">
</picture>

The run ends with order-check printing 1000|10000.0 after the replay; the amber rows show what the queue does when the worker cannot complete in time.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12 or newer (3.13 used) | the worker and its tests |
| SQLite shell (`sqlite3`) | 3.37 or newer (tables use `STRICT`) | `make db`, `make queries` (the worker itself uses Python's `sqlite3`) |
| Terraform | 1.9 or newer (1.17 used) | the infrastructure |
| Azure CLI | 2.60 or newer (2.84 used) | the runbook scripts |
| Docker | any recent | `make docker-smoke`, and the local build fallback |
| `uv` or `checkov` | checkov 3.3.30 | `make scan` (`uvx` runs it without installing) |
| `tflint` | 0.59 or newer | `make lint` runs it when installed (CI always does) |
| `shellcheck`, `jq`, `curl` | any | the scripts |
| An Azure subscription | needed only for the deploy section | none of the offline commands touch Azure |

## Setup, run, test, stop

Offline (no Azure, works on a Mac as written):

```bash
make install        # creates .venv from the hash-pinned requirements-dev.lock
make demos          # the whole lesson on a simulated Service Bus, in seconds (see below)
make test           # unit, integration (real SQLite, four processes) and end-to-end tests with coverage
make lint           # ruff, ruff format, mypy --strict, import-linter, shellcheck, terraform fmt, tflint
make validate       # terraform init -backend=false, validate, then terraform test for every module and the environment
make scan           # checkov over infra/, the Dockerfile and the workflow
make docker-smoke   # builds the image; checks non-root, the packaged SQL and fail-fast configuration
```

`make demos` prints, in order, the lesson's expected numbers. Each line is a real run of the same use cases the worker uses, on `order_worker.infrastructure.simulation`:

```text
make demo-baseline     step 1  1000|10000.0   OK: exactly the expected end state
make demo-duplicates   step 2  1100|11000.0   (100 commands applied twice; naive mode, 30 s lock, a 45 s command in ten)
                       step 3  1000|10000.0   (idempotent: 100 repeats skipped, 100 lock errors logged)
                       step 3  1000|10000.0   (idempotent and renewing: no lock lost at all)
make demo-sessions     step 4  without sessions c01 seq 10 applied after seq 16;  with sessions: OK
make demo-poison       steps 5, 6  one dead letter "InvalidAmount"; fixed and replayed once: 1001|10010.0, o-bad rows = 1
```

The SQL scripts also run with the sqlite3 shell: `make db migrate queries` (see [The SQL](#the-sql)).

`make help` lists every target. `make check` is `lint`, `test` and `validate` together; the CI workflow runs it, plus `make audit` (pip-audit on the locked dependencies) and `make scan`.

## Deploy to Azure

Run this once the subscription exists. Nothing is billed until `make up`.

**Cost.** Estimates from Azure's published prices as I know them in October 2026; confirm in the pricing calculator. The Standard namespace is the main cost: a base charge of about 10 US dollars a month (about 0.33 dollars a day) that runs whether or not a message is sent. Over the nine practice hours, with everything torn down at the end, expect well under one US dollar. Left up for a month, about 16 dollars.

| Resource | Billing | Idle cost |
|---|---|---|
| Service Bus namespace, Standard | monthly base charge, includes 13 million operations | about 0.33 dollars a day |
| Container Apps (one replica, 0.25 vCPU, always on) | per second of use, with a monthly free grant | about 2 to 3 dollars a month |
| Container Registry (Basic) | per day | about 0.17 dollars a day |
| Log Analytics (PerGB2018) | per GB ingested, first 5 GB a month free | about 0 |
| Managed identities, role assignments, budget, alert rule | free (an alert rule costs cents) | 0 |

**Commands**, in the lesson's order. Each script is idempotent and prints what it does.

```bash
az login
export ALERT_EMAIL=you@example.com             # budget and dead-letter alerts go here

make up                                         # scripts/provision.sh: registers providers, writes terraform.tfvars from your az session,
                                                #   terraform apply (group, workspace, identities, namespace with orders and orders-sessions,
                                                #   registry, role assignments, alert, budget), prints the queue properties
eval "$(scripts/env.sh)"                        # exports SB_NAMESPACE and LEDGER_PATH from the Terraform outputs

# step 1: build the worker, check the end state
make db                                         # creates data/orders.db (the worker would do it too)
make produce                                    # 1,000 commands and 1 poison command
MODE=naive make worker                          # on your laptop with your az login; Ctrl+C stops it gracefully; --until-idle works too
make check-azure                                # 1000|10000.0, MISMATCH lines if not

# step 2: duplicates from lock expiry (the queue's lock is 30 s; one command in ten takes 45 s)
make db reset-db && make produce
MODE=naive SLOW_EVERY=10 SLOW_SECONDS=45 LOCK_RENEWAL_SECONDS=0 make worker
make check-azure; make queries                  # 1100|11000.0; the log shows delivery_count=2 and "the lock supplied is invalid"

# step 3: idempotence, then renewal
make db reset-db && make produce
MODE=idempotent SLOW_EVERY=10 LOCK_RENEWAL_SECONDS=0 make worker      # 1000 rows, lock errors remain
make db reset-db && make produce
MODE=idempotent SLOW_EVERY=10 LOCK_RENEWAL_SECONDS=300 make worker    # 1000 rows, no lock errors

# step 4: sessions with several instances
make db reset-db && USE_SESSIONS=1 make produce
make workers                                    # three workers on orders-sessions; prints how many lines say "out of order" (0) and runs the check

# steps 5 and 6: the poison command and the replay
make dlq                                        # shows o-bad with reason and description; answer f
make worker                                     # processes the fixed command once
.venv/bin/order-check --expected-rows 1001 --expected-total 10010.0     # the poison command is now a row too

# the managed-identity path: the worker as a container app (its identity holds only Data Receiver)
make deploy                                     # builds the image in the registry and adds the container app

make down                                       # terraform destroy
```

On a subscription where ACR Tasks is not allowed (some free-trial subscriptions), use `BUILD_MODE=local make deploy`.

**Teardown.** `make down` runs `terraform destroy` (this also removes the subscription-scoped budget), prints `az group exists`, and reminds you that a namespace has no soft delete: it is gone at once and stops billing. Check the portal for leftovers named `sb-orders-*`, `acrorders*`, `rg-orders`.

## The SQL

SQLite is the lesson's "small database". The scripts are numbered and the worker applies them itself at start-up (every statement is idempotent); the same files run with the sqlite3 shell:

```bash
make db        # sql/001_schema.sql (DDL) and sql/002_seed.sql (DML: the 20 customers), into data/orders.db
make migrate   # sql/migrations/001_processed_messages.sql: the step 3 idempotency table
make queries   # sql/003_queries.sql: the lesson's end-state check, duplicate and out-of-order finders
make reset-db  # sql/reset.sql: empty ledger, no processed_messages
```

| File | Content |
|---|---|
| `sql/001_schema.sql` | `customers` and `ledger` (integer cents, `STRICT`, a deliberate absence of a unique key on `order_id` for steps 1 and 2) |
| `sql/002_seed.sql` | customers c01 to c20 |
| `sql/003_queries.sql` | seven queries, each with a one-line comment: totals, duplicates, redeliveries, per-customer order violations, gaps, per-customer totals, the `o-bad` row |
| `sql/migrations/001_processed_messages.sql` | `processed_messages (message_id PRIMARY KEY)`, written in the same transaction as the ledger row |
| `sql/reset.sql` | between runs |

## Done when: the lesson's checklist and the proof for each line

"Offline" means proven by a command in this repository with no subscription. "Subscription" means the commands in Deploy.

| Lesson step and its Done when | Offline proof | Subscription proof |
|---|---|---|
| **1. Build the worker.** 1,000 commands from the producer end up in the database exactly as expected. | `make demo-baseline`; `tests/e2e` `test_step_1_*`; `CheckLedger` unit tests; completion happens after the commit (`test_the_message_is_completed_only_after_the_ledger_write`) | `make produce`, `make worker`, `make check-azure` |
| **2. Cause duplicates with lock expiry.** Logs show those commands delivered more than once, and the database shows the duplicate effect. | `make demo-duplicates` (first run: `1100\|11000.0`, `delivery_count=2`, `the lock supplied is invalid`); `test_step_2_*` | step 2 commands above; `az servicebus queue show` prints `PT30S` and 10 (`scripts/show-queues.sh`) |
| **3. Idempotent processing and lock renewal.** A rerun of step 2 produces no duplicate effects; you can say which change would be enough alone and why you keep both. | `make demo-duplicates` (second and third run); `test_step_3_*`: idempotence alone fixes the effect but not the lost locks; renewal alone prevents redelivery in this run; `test_step_3_a_crash_after_the_commit_*` shows the case only idempotence covers | step 3 commands above |
| **4. Keep order per customer with sessions.** With several worker instances, each customer's commands apply in order, checked by a sequence number per customer. | `make demo-sessions`: four workers, one stalls on a command of c01; without sessions c01 is out of order, with sessions the check is clean; `test_step_4_*` | `make workers` and the `out of order` count of 0 |
| **5. Send poison to the dead-letter queue.** The message appears in the dead-letter queue with your reason and description, and other messages keep flowing. | `make demo-poison`; `test_step_5_*`; the queue's own max-delivery path: `test_a_message_that_keeps_failing_is_dead_lettered_by_the_queue_*` | `make dlq` shows `reason=InvalidAmount description="amount is not a number"` |
| **6. Replay and write the runbook.** The fixed command is processed once, and the runbook entry lists the signal, cause and fix for each of the three failures. | `make demo-poison` (a second replay finds nothing; one `o-bad` row); `test_step_6_*`; [docs/RUNBOOK.md](docs/RUNBOOK.md) has the table | `make dlq`, `make worker`, `order-check --expected-rows 1001 ...` |

| Lesson review checklist line | Where |
|---|---|
| Complete only after the database commit | `HandleDelivery` and its test; ARCHITECTURE.md decision 3 |
| The identity holds only Data Receiver on the queue | `infra` environment test `the_worker_holds_only_data_receiver_one_per_queue_and_never_the_owner_role`; `role_assignments` refuses the owner role |
| A duplicate delivery and a duplicate effect seen before the fix | step 2 |
| The message id goes into the same transaction as the result | `SqliteLedger.apply`; `tests/integration/test_sqlite_ledger.py` |
| Lock renewal on, and why both fixes stay | step 3 and ARCHITECTURE.md decision 4 |
| Several workers keep each customer's order, checked with the sequence number | step 4; `CheckLedger` and `sql/003_queries.sql` query 4 |
| Poison goes to the dead-letter queue with a reason while others keep flowing | step 5 |
| The runbook has signal, cause and fix for each of the three failures | docs/RUNBOOK.md |

### What was verified without a subscription

Run on 2026-10-27 (the exact commands and results are in the repository history and the build report): `make lint`, `make test`, `make validate`, `make scan`, `make demos` and the fresh-clone test. **Pending capacity:** the image build and smoke test did not complete (the container network stalled while the shared machine was overloaded). Run `make docker-smoke` once the machine has capacity; it checks the non-root user, the packaged SQL and the fail-fast configuration. The worker's fail-fast exit code 2 was checked outside Docker. What these cannot show is Azure's own behavior: that real Service Bus redelivers after exactly the lock duration, the exact text of its errors, the SDK's lock-renewal timing, whether sessions behave as modeled when a session lock expires, and the regional quota for Container Apps. The simulator models the rules the lesson depends on; the first live run is the check of the model (see ARCHITECTURE.md, "Limits of the teaching build").

## Stretch goals

| Stretch | Built? |
|---|---|
| Compare a receive-and-delete consumer with peek-lock and show which messages it can lose on a crash | No. `SimulatedBroker` has no receive-and-delete mode; adding one is a flag on `_Receiver` that removes the message at receipt. |
| Scheduled messages for a retry with a delay instead of an immediate abandon | No. The `Delivery` port would gain `abandon_later(seconds)`. |
| The same flow on Event Hubs, and what changes about ordering and replay | No. Written up as the comparison in ARCHITECTURE.md, "How to extend it". |

## What is simplified for teaching

- SQLite is the ledger. Several local processes share one file (WAL mode); in Azure the container app keeps its ledger on an ephemeral volume, one replica, so the cross-instance checks (step 4) run from your laptop with `make workers`.
- One environment (`dev`), local Terraform state. `backend.hcl.example` shows the remote state setup.
- The namespace keeps its public endpoint: private endpoints need the Premium tier. Access is Entra ID only (`local_auth_enabled = false`), so there are no keys to leak.
- The simulated broker is a teaching model, not an emulator: no message expiry, no scheduled messages, no duplicate detection, and a session lock does not expire on its own.
- The `slow` command and the lock settings are knobs for the lesson (`SLOW_EVERY`); they are off by default.

## Project structure

```text
azure-service-bus-worker/
  src/order_worker/
    domain/            order commands and their validation, ordering rule, repair, errors; depends on nothing
    application/       HandleDelivery, RunWorker, ProduceOrders, ReplayDeadLetters, CheckLedger and their ports; depends on domain
    infrastructure/    Service Bus adapters, SQLite ledger, simulated broker and scenarios, settings, logging, health, shutdown; depends on both
    interfaces/        the programs: order-worker, order-produce, order-dlq, order-check, order-simulate; depends on all, nothing depends on it
  tests/
    unit/              by layer, with hand-written fakes and SDK stubs
    integration/       the real SQLite ledger (including four processes at once); the live Azure test (skipped unless asked)
    e2e/               the lesson's steps through the use cases and the simulation program
  sql/                 001_schema, 002_seed, 003_queries, migrations/, reset
  infra/
    modules/           one module per reusable piece, each with a README and tftest tests
      log_analytics/  user_assigned_identity/  servicebus/  role_assignments/  container_registry/  worker_app/  budget/
    environments/dev/  the composition: variables, providers, outputs, tfvars example, tests
  scripts/             the lesson's runbook as the commands you run once the subscription exists
  tech/                one note per technology the repository uses (31 files), taught from zero through this repository's own files; start at tech/README.md
  docs/                RUNBOOK.md and decision records (docs/adr)
  Dockerfile  Makefile  pyproject.toml  requirements*.lock  .tflint.hcl  .checkov.yaml  .github/workflows/ci.yml
```

The dependency rule (domain depends on nothing; application on domain; infrastructure on both; interfaces on all; nothing on interfaces) is enforced by `import-linter` in `make lint`; the Azure SDK and `sqlite3` are forbidden in domain and application, and the Azure SDK is forbidden in interfaces.

## Author and license

Sumit Srivastava. MIT, see [LICENSE](LICENSE).
