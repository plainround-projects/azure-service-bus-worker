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

-include .env
export

.PHONY: help install env lint format test test-integration test-e2e test-azure audit check validate tf-test scan \
        demo-baseline demo-duplicates demo-sessions demo-poison demos db migrate queries reset-db docker-build docker-smoke \
        up deploy produce worker workers dlq check-azure down clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

# ---------------------------------------------------------------- offline: the lesson's failures on a simulated broker
demo-baseline: $(STAMP) ## step 1: 1,000 commands, no slow ones: the ledger is exactly right
	$(VENV)/bin/order-simulate --expect clean duplicates --mode naive --slow-every 0

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

# ---------------------------------------------------------------- the SQL scripts, with the sqlite3 shell
db: ## apply sql/001_schema.sql and sql/002_seed.sql to $(DB)
	@mkdir -p $(dir $(DB))
	$(SQLITE) < sql/001_schema.sql
	$(SQLITE) < sql/002_seed.sql

migrate: ## apply sql/migrations/*.sql (adds processed_messages: step 3)
	@for file in sql/migrations/*.sql; do echo "applying $$file"; $(SQLITE) < $$file; done

queries: ## run sql/003_queries.sql against $(DB)
	$(SQLITE) < sql/003_queries.sql

reset-db: ## empty the ledger (and drop processed_messages)
	$(SQLITE) < sql/reset.sql

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

format: $(STAMP) ## apply ruff's formatting and safe fixes, and terraform fmt
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
	terraform fmt -recursive infra

# Unit tests need no Azure and no services. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit, integration (real SQLite) and end-to-end (simulated broker) tests with coverage
	$(PY) -m pytest tests/unit tests/integration tests/e2e --cov=order_worker --cov-report=term
	$(PY) -m coverage report --include='src/order_worker/domain/*,src/order_worker/application/*' --fail-under=95

test-integration: $(STAMP) ## the real SQLite ledger, including concurrent processes
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the three failures through the command-line programs
	$(PY) -m pytest tests/e2e -m e2e

test-azure: $(STAMP) ## the real adapters against the deployed namespace (after make up; needs az login)
	RUN_AZURE_TESTS=1 $(PY) -m pytest tests/integration -m azure

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

validate: ## terraform init -backend=false and validate for the environment, then terraform test for every module and the environment
	cd $(TF_ENV) && terraform init -backend=false -input=false >/dev/null && terraform validate
	$(MAKE) --no-print-directory tf-test

tf-test: ## terraform test: plans and applies each module and the environment against a mocked azurerm provider (no credentials)
	@set -e; for dir in infra/modules/* $(TF_ENV); do \
	  echo "== terraform test $$dir"; \
	  (cd $$dir && terraform init -backend=false -input=false >/dev/null && terraform test); \
	done

scan: ## checkov over infra/, the Dockerfile and the workflow
	$(CHECKOV) --config-file .checkov.yaml --quiet --compact

check: lint test validate ## everything that needs no Azure

docker-build: ## build the worker image
	docker build -t azure-service-bus-worker:dev .

docker-smoke: docker-build ## run the image's offline simulation and the health endpoint as a non-root user
	scripts/docker-smoke.sh azure-service-bus-worker:dev

# ---------------------------------------------------------------- Azure (after the subscription exists)
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

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage dist data
	find infra -name .terraform -type d -prune -exec rm -rf {} +
