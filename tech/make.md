# GNU Make

*The one command per job: `make demos`, `make test`, `make lint`, `make up`. Pinned here: GNU Make 3.81 (the version macOS ships).*

## What it is

Make is a tool that runs named recipes. You write them in a file called `Makefile`. Each recipe is a **target** (a name), its **prerequisites** (what must exist or run first) and a **recipe** (the shell commands). `make test` finds the target `test` and runs it. The Makefile gives a project one memorable command per job.

## Why this repository uses it

A reader only needs `make demos`, `make test` and a few more. The Makefile is also what CI runs.

## Where it appears

| File | What it does with it |
|---|---|
| `Makefile` | All targets. |

## How it works underneath

Make reads the Makefile and builds a graph of targets. When you ask for a target, it first builds each prerequisite, then runs the recipe. If a target is a **file** and it is newer than its prerequisites, Make skips it; that is how `.venv/.installed` avoids reinstalling the packages each time. A target that is only a name, not a file, is listed under `.PHONY` so Make always runs it.

Every line of a recipe is run in its own shell. Lines must start with a **tab**. `$(VAR)` is a Make variable; `$$` writes a literal `$` for the shell (`$$RANDOM`). `?=` sets a variable only if it is not already set. `-include .env` reads variables from a file if it exists, and `export` passes all Make variables to the commands. A `## text` comment after a target is read by the `help` target to print a menu.

The Makefile on this Mac is run by GNU Make 3.81, so it uses no newer features.

## Walkthrough of this repository's use

### Variables

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
TF_ENV := infra/environments/dev
CHECKOV ?= uvx --from checkov==3.3.30 checkov
DB ?= data/orders.db
SQLITE := sqlite3 $(DB)
```

`PYTHON ?= $(shell command -v python3.13 || ...)` picks the newest Python unless you set it. `?=` sets a variable only if it is not already set; `:=` evaluates it now. `DB ?= data/orders.db` is the ledger path used by the SQL targets.

### Demos

```make
demo-duplicates: $(STAMP) ## steps 1 to 3: duplicates from lock expiry, then idempotence, then lock renewal
	$(VENV)/bin/order-simulate --expect dirty duplicates --mode naive
	$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent
	$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent --renew 300

demo-sessions: $(STAMP) ## step 4: four workers, one stalls; order breaks without sessions and holds with them
	$(VENV)/bin/order-simulate --expect dirty ordering
	$(VENV)/bin/order-simulate --expect clean ordering --sessions

demo-poison: $(STAMP) ## steps 5 and 6: the poison command is dead-lettered, then fixed and replayed exactly once
	$(VENV)/bin/order-simulate --expect clean poison

demos: demo-baseline demo-duplicates demo-sessions demo-poison ## the whole lesson, offline
```

Each demo target runs the simulation program with `--expect dirty` or `--expect clean`, which makes the command fail if the outcome is not the one the lesson predicts. `demos` is a target with no recipe, only prerequisites: it runs the other four in order.

### The SQL targets

```make
db: ## apply sql/001_schema.sql and sql/002_seed.sql to $(DB)
	@mkdir -p $(dir $(DB))
	$(SQLITE) < sql/001_schema.sql
	$(SQLITE) < sql/002_seed.sql

migrate: ## apply sql/migrations/*.sql (adds processed_messages: step 3)
	@for file in sql/migrations/*.sql; do echo "applying $$file"; $(SQLITE) < $$file; done

queries: ## run sql/003_queries.sql against $(DB)
	$(SQLITE) < sql/003_queries.sql

reset-db: ## empty the ledger (and drop processed_messages)
```

`@mkdir -p $(dir $(DB))` creates the folder (`$(dir ...)` takes the directory part; the leading `@` hides the command). `$(SQLITE) < sql/001_schema.sql` runs a file through the `sqlite3` shell. `migrate` loops over `sql/migrations/*.sql` with a shell `for`; `$$file` has two dollar signs because Make would otherwise consume one.

### Stamp file and lint

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

`.venv/.installed` is a file target: Make re-creates the environment only when the lock file or `pyproject.toml` is newer.

```make
lint: $(STAMP) ## ruff, mypy, import-linter, shellcheck, terraform fmt, tflint
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports
	shellcheck -x -P SCRIPTDIR scripts/*.sh
	terraform fmt -check -recursive infra
	@if command -v tflint >/dev/null; then \
	  tflint --init --config "$(CURDIR)/.tflint.hcl" >/dev/null && tflint --chdir infra --recursive --minimum-failure-severity=warning --config "$(CURDIR)/.tflint.hcl"; \
```

The `@if command -v tflint ...; then ...; else echo "WARNING ..."; fi` is one shell command spread over several lines with trailing backslashes: it runs TFLint if installed and prints a visible warning if not.

### Azure targets

```make
up: ## provision the namespace, queues, identities and roles (needs az login; see README Deploy)
	scripts/provision.sh

deploy: ## build the worker image in the registry and add the container app
	scripts/build-and-deploy.sh

produce: $(STAMP) ## step 1: send 1,000 commands and the poison command (USE_SESSIONS=1 for the session queue)
	$(VENV)/bin/order-produce

worker: $(STAMP) ## run one worker on your laptop against the real queue (az login identity); Ctrl+C stops it gracefully
	$(VENV)/bin/order-worker

workers: ## step 4: three workers in parallel on the session queue
	scripts/run-workers.sh 3

dlq: $(STAMP) ## step 6: the dead-letter replay tool
	$(VENV)/bin/order-dlq

check-azure: $(STAMP) ## compare the local ledger with the lesson's correct end state
	$(VENV)/bin/order-check

down: ## destroy everything
	scripts/teardown.sh
```

`up`, `deploy`, `produce`, `worker`, `workers`, `dlq`, `check-azure` and `down` call one script or program each. They are `.PHONY`: none is a file.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `Makefile`

111 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 10**

```make
# make help lists every target. Offline: install lint test validate scan demo-* db migrate queries.
# Azure (needs the subscription): up deploy produce worker workers dlq check-azure down.
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
TF_ENV := infra/environments/dev
CHECKOV ?= uvx --from checkov==3.3.30 checkov
DB ?= data/orders.db
SQLITE := sqlite3 $(DB)
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** A **virtual environment** is a private folder holding a copy of the Python interpreter and the libraries installed for one project. It keeps the project's libraries separate from the rest of the machine, so two projects can use different versions of the same library.

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

**New idea.** A **lock file** records the exact versions (and often the hashes) of every package a project uses, including packages that those packages need. Installing from it gives the same result on every machine and on every day.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `# make help lists every target. Offline: install lint test validate scan demo-* db migrate queries.`: Comment for the reader: make help lists every target. Offline: install lint test validate scan demo-* db migrate queries.
- `# Azure (needs the subscription): up deploy produce worker workers dlq check-azure down.`: Comment for the reader: Azure (needs the subscription): up deploy produce worker workers dlq check-azure down.
- `PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)`: A line `NAME := value` sets a variable once, when the Makefile is read. `NAME ?= value` sets it only if it is not already set (so you can override it: `make PORT=9000 run`). `$(NAME)` uses the variable. Sets the variable `PYTHON` (only if not already set). The Python interpreter used to create the virtual environment: the first of `python3.13`, `python3.12`, `python3` that exists (`command -v` prints a command's location, and `||` tries the next if it fails). `$(shell command)` runs the command when the Makefile is read and inserts its output.
- `VENV := .venv`: Sets the variable `VENV` (once, when the file is read). The folder of the **virtual environment** (a private copy of Python plus the project's libraries).
- `PY := $(VENV)/bin/python`: Sets the variable `PY` (once, when the file is read). The Python inside that environment.
- `STAMP := $(VENV)/.installed`: Sets the variable `STAMP` (once, when the file is read). A marker file inside the environment. It exists once the libraries are installed; make compares its age with the lock file to decide whether to reinstall.
- `TF_ENV := infra/environments/dev`: Sets the variable `TF_ENV` (once, when the file is read). The folder of the Terraform environment that the targets operate on.
- `CHECKOV ?= uvx --from checkov==3.3.30 checkov`: Sets the variable `CHECKOV` (only if not already set). How to run checkov: `uvx` fetches and runs a pinned version on demand. CI overrides the variable (`CHECKOV=checkov`) because it installs checkov itself.
- `DB ?= data/orders.db`: Sets the variable `DB` (only if not already set). The path of the SQLite database file.
- `SQLITE := sqlite3 $(DB)`: Sets the variable `SQLITE` (once, when the file is read). The `sqlite3` command-line shell pointed at that database.

**Lines 12 to 13**

```make
-include .env
export
```

- `-include .env`: `-include .env` reads the file `.env` if it exists (the leading `-` means "no error if it is missing"), and `export` passes every variable to the commands that make runs as environment variables.
- `export`: Marks every variable to be passed to the commands as an environment variable (see the line above).

**Lines 15 to 17**

```make
.PHONY: help install env lint format test test-integration test-e2e test-azure audit check validate tf-test scan \
        demo-baseline demo-duplicates demo-sessions demo-poison demos db migrate queries reset-db docker-build docker-smoke \
        up deploy produce worker workers dlq check-azure down clean
```

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

- `.PHONY: help install env lint format test test-integration test-e2e test-azure audit check validate tf-test sc`: `.PHONY` lists the targets that are tasks, not files. Here are the names.

**Lines 19 to 20**

```make
help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```

**New idea.** A **regular expression** is a compact pattern for matching text: `[a-z]` is one lowercase letter, `+` means one or more, `^` and `$` mark the start and end, `{1,127}` means one to 127 repeats.

- `help: ## list the targets`: **make** is a program that runs named tasks defined in a file called `Makefile`. You run a task with `make <name>`. Each task (a **target**) lists what must be done before it (its **prerequisites**) and the shell commands to run (its **recipe**, whose lines must start with a tab character). A line `name: prerequisites` defines a target. Before running the recipe, make runs every prerequisite that is itself a target. If the target is the name of a *file*, make skips the recipe when the file is newer than all its prerequisites; the targets listed after `.PHONY` are not files, so they always run. Defines the target `help`. Description (shown by `make help`): list the targets. The text after `##` on a target line is a one-line description; the `help` target prints these.
- `@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort`: Prints the help. `grep -E` selects (with an extended regular expression) the lines that look like `target: ... ## description`; `$(MAKEFILE_LIST)` is the list of Makefiles; the pipe `|` hands the lines to `sed`, which replaces everything from the colon through `## ` with a tab; `sort` puts them in alphabetical order. A recipe line that starts with `@` is run without printing the command first.

**Lines 22 to 26**

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

**New idea.** A **hash** (or *digest*) is a fixed-length fingerprint calculated from some data. The same data always gives the same hash and any change gives a different one, so comparing hashes shows whether a file or an image is exactly the one that was reviewed.

- `$(STAMP): requirements-dev.lock pyproject.toml`: Defines the target `$(STAMP)`. Its prerequisites: `requirements-dev.lock`, `pyproject.toml`. This target is the marker file: it is rebuilt whenever the lock file or `pyproject.toml` is newer than it.
- `$(PYTHON) -m venv $(VENV)`: Creates the virtual environment in the folder `.venv` (`-m venv` runs Python's built-in module for that).
- `$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock`: Installs exactly the packages in the lock file. `-q` keeps the output quiet, `-r` reads the list from a file, and `--require-hashes` makes pip refuse any package whose fingerprint (hash) is not recorded in the file, so a tampered or substituted package cannot be installed.
- `$(VENV)/bin/pip install -q --no-deps -e .`: Installs this project itself. `-e` (editable) links the source folder instead of copying it, so edits take effect at once; `--no-deps` stops pip from choosing dependencies on its own, because the lock file already installed exactly the right ones.
- `touch $@`: Creates (or refreshes the time of) the marker file, so make knows the install is up to date. `$@` inside a recipe is the name of the target being built.

**Line 28**

```make
install: $(STAMP) ## create .venv from the lock file
```

- `install: $(STAMP) ## create .venv from the lock file`: Defines the target `install`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): create .venv from the lock file.

**Lines 30 to 31**

```make
env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
```

- `env:`: Defines the target `env`.
- `@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }`: If the file `.env` does not exist (`[ -f .env ]` tests that a regular file exists), copy the template to it and say so. `||` means "run the right side only if the left side failed".

**Lines 33 to 35**

```make
# ---------------------------------------------------------------- offline: the lesson's failures on a simulated broker
demo-baseline: $(STAMP) ## step 1: 1,000 commands, no slow ones: the ledger is exactly right
	$(VENV)/bin/order-simulate --expect clean duplicates --mode naive --slow-every 0
```

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

- `# ---------------------------------------------------------------- offline: the lesson's failures on a simulat`: A comment line used as a divider between sections of the file: offline: the lesson's failures on a simulated broker
- `demo-baseline: $(STAMP) ## step 1: 1,000 commands, no slow ones: the ledger is exactly right`: Defines the target `demo-baseline`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): step 1: 1,000 commands, no slow ones: the ledger is exactly right.
- `$(VENV)/bin/order-simulate --expect clean duplicates --mode naive --slow-every 0`: Runs the simulation of the duplicates scenario in the naive mode with no slow messages, expecting a clean ledger.

**Lines 37 to 40**

```make
demo-duplicates: $(STAMP) ## steps 1 to 3: duplicates from lock expiry, then idempotence, then lock renewal
	$(VENV)/bin/order-simulate --expect dirty duplicates --mode naive
	$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent
	$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent --renew 300
```

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

**New idea.** A **lock** lets only one thread at a time into a protected piece of code, so two threads cannot change the same data at the same moment.

- `demo-duplicates: $(STAMP) ## steps 1 to 3: duplicates from lock expiry, then idempotence, then lock renewal`: Defines the target `demo-duplicates`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): steps 1 to 3: duplicates from lock expiry, then idempotence, then lock renewal.
- `$(VENV)/bin/order-simulate --expect dirty duplicates --mode naive`: Runs the duplicates scenario in naive mode and expects the ledger to be wrong (duplicates present); the command succeeds only if the problem shows up.
- `$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent`: Runs the duplicates scenario with idempotent processing and expects a clean ledger.
- `$(VENV)/bin/order-simulate --expect clean duplicates --mode idempotent --renew 300`: The same with lock renewal enabled (a lock kept alive for up to 300 seconds).

**Lines 42 to 44**

```make
demo-sessions: $(STAMP) ## step 4: four workers, one stalls; order breaks without sessions and holds with them
	$(VENV)/bin/order-simulate --expect dirty ordering
	$(VENV)/bin/order-simulate --expect clean ordering --sessions
```

- `demo-sessions: $(STAMP) ## step 4: four workers, one stalls; order breaks without sessions and holds with them`: Defines the target `demo-sessions`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): step 4: four workers, one stalls; order breaks without sessions and holds with them.
- `$(VENV)/bin/order-simulate --expect dirty ordering`: Runs the ordering scenario without sessions and expects out-of-order effects.
- `$(VENV)/bin/order-simulate --expect clean ordering --sessions`: Runs the ordering scenario with sessions and expects per-customer order to hold.

**Lines 46 to 47**

```make
demo-poison: $(STAMP) ## steps 5 and 6: the poison command is dead-lettered, then fixed and replayed exactly once
	$(VENV)/bin/order-simulate --expect clean poison
```

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

- `demo-poison: $(STAMP) ## steps 5 and 6: the poison command is dead-lettered, then fixed and replayed exactly o`: Defines the target `demo-poison`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): steps 5 and 6: the poison command is dead-lettered, then fixed and replayed exactly once.
- `$(VENV)/bin/order-simulate --expect clean poison`: Runs the poison-message scenario and expects it to end clean (dead-lettered, fixed, replayed once).

**Line 49**

```make
demos: demo-baseline demo-duplicates demo-sessions demo-poison ## the whole lesson, offline
```

- `demos: demo-baseline demo-duplicates demo-sessions demo-poison ## the whole lesson, offline`: Defines the target `demos`. Its prerequisites: `demo-baseline`, `demo-duplicates`, `demo-sessions`, `demo-poison`. Description (shown by `make help`): the whole lesson, offline.

**Lines 51 to 55**

```make
# ---------------------------------------------------------------- the SQL scripts, with the sqlite3 shell
db: ## apply sql/001_schema.sql and sql/002_seed.sql to $(DB)
	@mkdir -p $(dir $(DB))
	$(SQLITE) < sql/001_schema.sql
	$(SQLITE) < sql/002_seed.sql
```

- `# ---------------------------------------------------------------- the SQL scripts, with the sqlite3 shell`: A comment line used as a divider between sections of the file: the SQL scripts, with the sqlite3 shell
- `db: ## apply sql/001_schema.sql and sql/002_seed.sql to $(DB)`: Defines the target `db`. Description (shown by `make help`): apply sql/001_schema.sql and sql/002_seed.sql to $(DB).
- `@mkdir -p $(dir $(DB))`: Makes the folder that will hold the database (`-p`: no error if it exists; `$(dir ...)` is make's function for the folder part of a path).
- `$(SQLITE) < sql/001_schema.sql`: Feeds the schema script to the `sqlite3` shell (`<` means: take the command's input from this file).
- `$(SQLITE) < sql/002_seed.sql`: Feeds the seed script to the `sqlite3` shell.

**Lines 57 to 58**

```make
migrate: ## apply sql/migrations/*.sql (adds processed_messages: step 3)
	@for file in sql/migrations/*.sql; do echo "applying $$file"; $(SQLITE) < $$file; done
```

- `migrate: ## apply sql/migrations/*.sql (adds processed_messages: step 3)`: Defines the target `migrate`. Description (shown by `make help`): apply sql/migrations/*.sql (adds processed_messages: step 3).
- `@for file in sql/migrations/*.sql; do echo "applying $$file"; $(SQLITE) < $$file; done`: A shell loop over each migration file: print its name, then run it in the database. In a Makefile a doubled `$$` means a single `$` for the shell, because make would otherwise treat `$` as its own variable syntax.

**Lines 60 to 61**

```make
queries: ## run sql/003_queries.sql against $(DB)
	$(SQLITE) < sql/003_queries.sql
```

- `queries: ## run sql/003_queries.sql against $(DB)`: Defines the target `queries`. Description (shown by `make help`): run sql/003_queries.sql against $(DB).
- `$(SQLITE) < sql/003_queries.sql`: Runs the lesson's queries.

**Lines 63 to 64**

```make
reset-db: ## empty the ledger (and drop processed_messages)
	$(SQLITE) < sql/reset.sql
```

- `reset-db: ## empty the ledger (and drop processed_messages)`: Defines the target `reset-db`. Description (shown by `make help`): empty the ledger (and drop processed_messages).
- `$(SQLITE) < sql/reset.sql`: Empties the ledger.

**Lines 66 to 76**

```make
# ---------------------------------------------------------------- quality
lint: $(STAMP) ## ruff, mypy, import-linter, shellcheck, terraform fmt, tflint
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports
	shellcheck -x -P SCRIPTDIR scripts/*.sh
	terraform fmt -check -recursive infra
	@if command -v tflint >/dev/null; then \
	  tflint --init --config "$(CURDIR)/.tflint.hcl" >/dev/null && tflint --chdir infra --recursive --minimum-failure-severity=warning --config "$(CURDIR)/.tflint.hcl"; \
	else echo "WARNING: tflint is not installed here; the CI workflow runs it"; fi
```

- `# ---------------------------------------------------------------- quality`: A comment line used as a divider between sections of the file: quality
- `lint: $(STAMP) ## ruff, mypy, import-linter, shellcheck, terraform fmt, tflint`: Defines the target `lint`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): ruff, mypy, import-linter, shellcheck, terraform fmt, tflint.
- `$(VENV)/bin/ruff check .`: Runs ruff's linter on the whole project (`.` is the current folder) and fails if it finds problems.
- `$(VENV)/bin/ruff format --check .`: Checks that every Python file is already formatted the way ruff would format it, without changing any file.
- `$(VENV)/bin/mypy`: Runs the type checker. Which files to check comes from `pyproject.toml`.
- `$(VENV)/bin/lint-imports`: Runs import-linter, which checks the layering rules of the imports.
- `shellcheck -x -P SCRIPTDIR scripts/*.sh`: Runs shellcheck (a checker for shell scripts) on every script. `-x` lets it follow `source`d files, and `-P SCRIPTDIR` tells it to look for them next to each script.
- `terraform fmt -check -recursive infra`: Checks that the Terraform files under `infra` are formatted canonically (`-check` changes nothing, `-recursive` includes sub-folders).
- `@if command -v tflint >/dev/null; then \`: Starts a shell `if`: it tests whether the program `tflint` is installed (`command -v` prints its location; `>/dev/null` throws the output away).
- `tflint --init --config "$(CURDIR)/.tflint.hcl" >/dev/null && tflint --chdir infra --recursive --minimum-failure-severity=warning --config "$(CURDIR)/.`: Then: `tflint --init` downloads the rule plug-ins named in the config file; `&&` means "and, if that worked"; the second command lints everything under `infra` recursively, failing on findings of severity warning or worse. `$(CURDIR)` is the folder make is running in.
- `else echo "WARNING: tflint is not installed here; the CI workflow runs it"; fi`: Otherwise print a warning, so the check is not silently skipped; `fi` ends the `if`.

**Lines 78 to 81**

```make
format: $(STAMP) ## apply ruff's formatting and safe fixes, and terraform fmt
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
	terraform fmt -recursive infra
```

- `format: $(STAMP) ## apply ruff's formatting and safe fixes, and terraform fmt`: Defines the target `format`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): apply ruff's formatting and safe fixes, and terraform fmt.
- `$(VENV)/bin/ruff check --fix .`: Lets ruff fix the problems it can fix safely.
- `$(VENV)/bin/ruff format .`: Rewrites the Python files in ruff's format.
- `terraform fmt -recursive infra`: Rewrites the Terraform files in the canonical format.

**Lines 83 to 86**

```make
# Unit tests need no Azure and no services. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit, integration (real SQLite) and end-to-end (simulated broker) tests with coverage
	$(PY) -m pytest tests/unit tests/integration tests/e2e --cov=order_worker --cov-report=term
	$(PY) -m coverage report --include='src/order_worker/domain/*,src/order_worker/application/*' --fail-under=95
```

**New idea.** **Code coverage** measures which lines (and branches) of the program were run while the tests ran. A line the tests never reach is untested, so the project requires a high percentage for its core layers.

- `# Unit tests need no Azure and no services. The domain and application must stay at 95% coverage or more.`: Comment for the reader: Unit tests need no Azure and no services. The domain and application must stay at 95% coverage or more.
- `test: $(STAMP) ## unit, integration (real SQLite) and end-to-end (simulated broker) tests with coverage`: Defines the target `test`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): unit, integration (real SQLite) and end-to-end (simulated broker) tests with coverage.
- `$(PY) -m pytest tests/unit tests/integration tests/e2e --cov=order_worker --cov-report=term`: Runs the unit, integration (real SQLite) and end-to-end tests, measuring coverage of the package.
- `$(PY) -m coverage report --include='src/order_worker/domain/*,src/order_worker/application/*' --fail-under=95`: Prints coverage for the domain and application layers only, and fails under 95 percent.

**Lines 88 to 89**

```make
test-integration: $(STAMP) ## the real SQLite ledger, including concurrent processes
	$(PY) -m pytest tests/integration -m integration
```

**New idea.** A **process** is one running copy of a program. The operating system gives it its own memory and a number, its *pid*. Two processes do not share variables; they cooperate through files, network connections or signals.

- `test-integration: $(STAMP) ## the real SQLite ledger, including concurrent processes`: Defines the target `test-integration`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): the real SQLite ledger, including concurrent processes.
- `$(PY) -m pytest tests/integration -m integration`: Runs only the tests carrying the `integration` marker.

**Lines 91 to 92**

```make
test-e2e: $(STAMP) ## the three failures through the command-line programs
	$(PY) -m pytest tests/e2e -m e2e
```

- `test-e2e: $(STAMP) ## the three failures through the command-line programs`: Defines the target `test-e2e`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): the three failures through the command-line programs.
- `$(PY) -m pytest tests/e2e -m e2e`: Runs only the tests carrying the `e2e` marker.

**Lines 94 to 95**

```make
test-azure: $(STAMP) ## the real adapters against the deployed namespace (after make up; needs az login)
	RUN_AZURE_TESTS=1 $(PY) -m pytest tests/integration -m azure
```

- `test-azure: $(STAMP) ## the real adapters against the deployed namespace (after make up; needs az login)`: Defines the target `test-azure`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): the real adapters against the deployed namespace (after make up; needs az login).
- `RUN_AZURE_TESTS=1 $(PY) -m pytest tests/integration -m azure`: Runs the tests marked `azure`. The variable `RUN_AZURE_TESTS=1` is the explicit switch they require, so they never run by accident.

**Lines 97 to 98**

```make
audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
```

- `audit: $(STAMP) ## check the locked dependencies for known vulnerabilities`: Defines the target `audit`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): check the locked dependencies for known vulnerabilities.
- `$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock`: Checks every package in the lock file against a database of known vulnerabilities. `--no-deps --disable-pip` tell it to audit the file as written and not to install anything.

**Lines 100 to 102**

```make
validate: ## terraform init -backend=false and validate for the environment, then terraform test for every module and the environment
	cd $(TF_ENV) && terraform init -backend=false -input=false >/dev/null && terraform validate
	$(MAKE) --no-print-directory tf-test
```

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

- `validate: ## terraform init -backend=false and validate for the environment, then terraform test for every mod`: Defines the target `validate`. Description (shown by `make help`): terraform init -backend=false and validate for the environment, then terraform test for every module and the environment.
- `cd $(TF_ENV) && terraform init -backend=false -input=false >/dev/null && terraform validate`: Goes into the environment folder, downloads providers (`init`; `-backend=false` skips remote state, `-input=false` never asks questions; output discarded) and then checks that the configuration is internally consistent (`validate`).
- `$(MAKE) --no-print-directory tf-test`: Runs the `tf-test` target by starting make again (`$(MAKE)` is make itself); `--no-print-directory` suppresses the "entering directory" lines.

**Lines 104 to 108**

```make
tf-test: ## terraform test: plans and applies each module and the environment against a mocked azurerm provider (no credentials)
	@set -e; for dir in infra/modules/* $(TF_ENV); do \
	  echo "== terraform test $$dir"; \
	  (cd $$dir && terraform init -backend=false -input=false >/dev/null && terraform test); \
	done
```

- `tf-test: ## terraform test: plans and applies each module and the environment against a mocked azurerm provide`: Defines the target `tf-test`. Description (shown by `make help`): terraform test: plans and applies each module and the environment against a mocked azurerm provider (no credentials).
- `@set -e; for dir in infra/modules/* $(TF_ENV); do \`: A shell loop over every module folder and the environment. `set -e` makes the shell stop at the first failing command.
- `echo "== terraform test $$dir"; \`: Prints which folder is being tested.
- `(cd $$dir && terraform init -backend=false -input=false >/dev/null && terraform test); \`: In a sub-shell (the parentheses keep the `cd` from affecting the loop): enter the folder, initialize, and run `terraform test`, which runs the `.tftest.hcl` tests against a mocked provider.
- `done`: Ends the shell loop.

**Lines 110 to 111**

```make
scan: ## checkov over infra/, the Dockerfile and the workflow
	$(CHECKOV) --config-file .checkov.yaml --quiet --compact
```

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

- `scan: ## checkov over infra/, the Dockerfile and the workflow`: Defines the target `scan`. Description (shown by `make help`): checkov over infra/, the Dockerfile and the workflow.
- `$(CHECKOV) --config-file .checkov.yaml --quiet --compact`: Runs checkov with this project's configuration; `--quiet` shows only failures and `--compact` omits the code snippets.

**Line 113**

```make
check: lint test validate ## everything that needs no Azure
```

- `check: lint test validate ## everything that needs no Azure`: Defines the target `check`. Its prerequisites: `lint`, `test`, `validate`. Description (shown by `make help`): everything that needs no Azure.

**Lines 115 to 116**

```make
docker-build: ## build the worker image
	docker build -t azure-service-bus-worker:dev .
```

- `docker-build: ## build the worker image`: Defines the target `docker-build`. Description (shown by `make help`): build the worker image.
- `docker build -t azure-service-bus-worker:dev .`: Builds the container image from the `Dockerfile` in this folder and names it `azure-service-bus-worker:dev`.

**Lines 118 to 119**

```make
docker-smoke: docker-build ## run the image's offline simulation and the health endpoint as a non-root user
	scripts/docker-smoke.sh azure-service-bus-worker:dev
```

- `docker-smoke: docker-build ## run the image's offline simulation and the health endpoint as a non-root user`: Defines the target `docker-smoke`. Its prerequisites: `docker-build`. Description (shown by `make help`): run the image's offline simulation and the health endpoint as a non-root user.
- `scripts/docker-smoke.sh azure-service-bus-worker:dev`: Runs the smoke-test script on the image just built.

**Lines 121 to 123**

```make
# ---------------------------------------------------------------- Azure (after the subscription exists)
up: ## provision the namespace, queues, identities and roles (needs az login; see README Deploy)
	scripts/provision.sh
```

- `# ---------------------------------------------------------------- Azure (after the subscription exists)`: A comment line used as a divider between sections of the file: Azure (after the subscription exists)
- `up: ## provision the namespace, queues, identities and roles (needs az login; see README Deploy)`: Defines the target `up`. Description (shown by `make help`): provision the namespace, queues, identities and roles (needs az login; see README Deploy).
- `scripts/provision.sh`: Runs the script that creates the Azure resources.

**Lines 125 to 126**

```make
deploy: ## build the worker image in the registry and add the container app
	scripts/build-and-deploy.sh
```

**New idea.** A **container registry** is a server that stores container images under names and version tags. **Azure Container Registry (ACR)** is Azure's; a service pulls an image from it using an identity that holds the `AcrPull` role.

- `deploy: ## build the worker image in the registry and add the container app`: Defines the target `deploy`. Description (shown by `make help`): build the worker image in the registry and add the container app.
- `scripts/build-and-deploy.sh`: Runs the script that builds the image in the registry and adds the app.

**Lines 128 to 129**

```make
produce: $(STAMP) ## step 1: send 1,000 commands and the poison command (USE_SESSIONS=1 for the session queue)
	$(VENV)/bin/order-produce
```

- `produce: $(STAMP) ## step 1: send 1,000 commands and the poison command (USE_SESSIONS=1 for the session queue)`: Defines the target `produce`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): step 1: send 1,000 commands and the poison command (USE_SESSIONS=1 for the session queue).
- `$(VENV)/bin/order-produce`: Runs the producer program installed by the project.

**Lines 131 to 132**

```make
worker: $(STAMP) ## run one worker on your laptop against the real queue (az login identity); Ctrl+C stops it gracefully
	$(VENV)/bin/order-worker
```

**New idea.** A **graceful shutdown** lets a program finish the work it has started, close its connections and exit with code 0 when it is asked to stop, instead of being cut off in the middle of a task.

- `worker: $(STAMP) ## run one worker on your laptop against the real queue (az login identity); Ctrl+C stops it `: Defines the target `worker`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): run one worker on your laptop against the real queue (az login identity); Ctrl+C stops it gracefully.
- `$(VENV)/bin/order-worker`: Runs the worker program.

**Lines 134 to 135**

```make
workers: ## step 4: three workers in parallel on the session queue
	scripts/run-workers.sh 3
```

- `workers: ## step 4: three workers in parallel on the session queue`: Defines the target `workers`. Description (shown by `make help`): step 4: three workers in parallel on the session queue.
- `scripts/run-workers.sh 3`: Runs the script that starts three worker processes.

**Lines 137 to 138**

```make
dlq: $(STAMP) ## step 6: the dead-letter replay tool
	$(VENV)/bin/order-dlq
```

- `dlq: $(STAMP) ## step 6: the dead-letter replay tool`: Defines the target `dlq`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): step 6: the dead-letter replay tool.
- `$(VENV)/bin/order-dlq`: Runs the dead-letter tool.

**Lines 140 to 141**

```make
check-azure: $(STAMP) ## compare the local ledger with the lesson's correct end state
	$(VENV)/bin/order-check
```

- `check-azure: $(STAMP) ## compare the local ledger with the lesson's correct end state`: Defines the target `check-azure`. Its prerequisites: `$(STAMP)`. Description (shown by `make help`): compare the local ledger with the lesson's correct end state.
- `$(VENV)/bin/order-check`: Runs the ledger check.

**Lines 143 to 144**

```make
down: ## destroy everything
	scripts/teardown.sh
```

- `down: ## destroy everything`: Defines the target `down`. Description (shown by `make help`): destroy everything.
- `scripts/teardown.sh`: Runs the script that deletes everything.

**Lines 146 to 148**

```make
clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage dist data
	find infra -name .terraform -type d -prune -exec rm -rf {} +
```

- `clean:`: Defines the target `clean`.
- `rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage dist data`: Deletes the environment, caches, build folder and the local data folder.
- `find infra -name .terraform -type d -prune -exec rm -rf {} +`: Finds every folder named `.terraform` under `infra`, does not descend into it (`-prune`) and deletes it (`-exec rm -rf {} +` runs `rm` on all matches).


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `.github/workflows/ci.yml` | 28 to 29, 40, 47 | [github-actions.md](github-actions.md) |
| `tests/integration/test_azure_live.py` | 3 to 4 | [pytest.md](pytest.md) |
| `.editorconfig` | 14 | [editorconfig.md](editorconfig.md) |
| `infra/environments/dev/variables.tf` | 45 | [terraform.md](terraform.md) |
| `infra/modules/worker_app/variables.tf` | 86 | [terraform.md](terraform.md) |
| `pyproject.toml` | 67 | [pyproject-toml.md](pyproject-toml.md) |
| `scripts/provision.sh` | 39 | [bash.md](bash.md) |
| `sql/003_queries.sql` | 1 | [sql.md](sql.md) |
| `sql/migrations/001_processed_messages.sql` | 1 | [sql.md](sql.md) |
| `src/order_worker/infrastructure/sqlite_ledger.py` | 18 | [sqlite.md](sqlite.md) |

## Try it yourself

Print the menu from the `##` comments.

```bash
make help
```

You should see something like this:

```text
audit	check the locked dependencies for known vulnerabilities
check	everything that needs no Azure
check-azure	compare the local ledger with the lesson's correct end state
db	apply sql/001_schema.sql and sql/002_seed.sql to $(DB)
demo-baseline	step 1: 1,000 commands, no slow ones: the ledger is exactly right
demo-duplicates	steps 1 to 3: duplicates from lock expiry, then idempotence, then lock renewal
demo-poison	steps 5 and 6: the poison command is dead-lettered, then fixed and replayed exactly once
demo-sessions	step 4: four workers, one stalls; order breaks without sessions and holds with them
demos	the whole lesson, offline
deploy	build the worker image in the registry and add the container app
dlq	step 6: the dead-letter replay tool
docker-build	build the worker image
docker-smoke	run the image's offline simulation and the health endpoint as a non-root user
down	destroy everything
...
workers	step 4: three workers in parallel on the session queue
```

Show what a demo would run, without running it.

```bash
make -n demo-baseline
```

You should see something like this:

```text
.venv/bin/order-simulate --expect clean duplicates --mode naive --slow-every 0
```

Run the first demo (about a second).

```bash
make demo-baseline
```

You should see something like this:

```text
.venv/bin/order-simulate --expect clean duplicates --mode naive --slow-every 0
duplicates: mode=naive lock renewal=0s, 30 s lock, no slow commands
  handled=1000 applied=1000 skipped_duplicates=0 dead_lettered=0 lock_lost=0
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

Check the version.

```bash
make --version | head -1
```

You should see something like this:

```text
GNU Make 3.81
```

## Mistakes people make

- Spaces instead of a tab at the start of a recipe line: `*** missing separator`.
- Forgetting `.PHONY`, so a file named `test` would stop `make test` from running.
- Expecting `cd` on one recipe line to affect the next line. Each line is its own shell; join with `&&` or use `cd dir && command`.
- Writing `$RANDOM` instead of `$$RANDOM` and having Make eat the `$`.
- Putting logic in the Makefile that belongs in a script. Long steps live in `scripts/`.

## Check yourself

1. **What are a target, a prerequisite and a recipe?**
   Answer: The name you ask for, what must be built first, and the commands that build it.

2. **Why must recipe lines start with a tab?**
   Answer: That is how Make tells a recipe line from a Make directive.

3. **What does `.PHONY` do?**
   Answer: It marks targets that are names, not files, so they always run.

4. **What does `$$` mean?**
   Answer: A literal dollar sign passed to the shell.

5. **Why does `.venv/.installed` exist?**
   Answer: It is a file target; Make reinstalls only when the lock file or `pyproject.toml` is newer.

## Further reading

- GNU Make manual (3.81 is used on the author's Mac): https://www.gnu.org/software/make/manual/make.html
