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
