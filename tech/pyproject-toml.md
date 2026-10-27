# pyproject.toml and TOML

*The one configuration file of the Python project. Pinned here: TOML 1.0, setuptools build backend.*

## What it is

`pyproject.toml` is the one configuration file of a modern Python project. It is written in **TOML**, a plain text format of `key = value` lines grouped under `[section]` headings. The file names the project, lists its dependencies, says how to build it, and holds the settings of tools such as ruff, mypy and pytest.

## Why this repository uses it

Every tool in the repository reads its settings from this file, so the project's rules are in one reviewable place.

## Where it appears

| File | What it does with it |
|---|---|
| `pyproject.toml` | Project metadata, dependencies, five console scripts and the settings of ruff, mypy, pytest, coverage and import-linter. |

## How it works underneath

TOML has a few building blocks. `key = "text"` is a string, `key = 120` a number, `key = true` a boolean, `key = ["a", "b"]` a list. `[table]` starts a group of keys. `[[array.of.tables]]` starts one more entry in a list of groups; each repetition adds an item.

Python tools look for their own table: `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`. The `[build-system]` table tells pip which build backend (here setuptools) turns the source into an installable package, and `[project]` holds the name, version, Python requirement and dependencies.

## Walkthrough of this repository's use

### Build system and project

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "azure-service-bus-worker"
version = "0.1.0"
description = "An Azure Service Bus order worker that shows duplicates from lock expiry, per-customer ordering with sessions and poison messages on purpose, with its dead-letter replay tool and the Azure infrastructure as Terraform."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
```

`[build-system]` names the backend (`setuptools`) pip uses to build the package. `[project]` holds the name, version, a description, the readme and the Python requirement (`requires-python = ">=3.12"`). `license = { text = "MIT" }` is an inline table (a table written on one line). `authors` is a list of such tables.

### Optional dependencies

```toml
[project.optional-dependencies]
```

A group named `dev` holds the tools only developers need. `uv pip compile --extra dev` includes it in `requirements-dev.lock`.

### Finding the package

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

Tells setuptools to look for packages in `src/` (the "src layout"), which keeps the importable code separate from tests and scripts.

### Tool tables

The rest are `[tool.<name>]` tables: ruff, mypy, pytest, coverage, importlinter. Each tool reads only its own table. `[[tool.importlinter.contracts]]` (double brackets) is a list of tables: each repetition adds one contract.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `pyproject.toml`

87 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 3**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

- `[build-system]`: **TOML** is a configuration format. A line `[name]` starts a **table** (a group of settings); under it, `key = value` lines set the settings. Values are text in double quotes, numbers, `true` or `false`, or lists in square brackets. A `[[name]]` header (double brackets) adds one more entry to a list of tables. A `#` starts a comment. Starts the table `build-system`: How to build this project into an installable package: which tool is needed and which of its entry points does the work.
- `requires = ["setuptools>=75"]`: `requires`: The tools needed to build the package. `setuptools>=75` means setuptools, version 75 or newer. Here: `["setuptools>=75"]`.
- `build-backend = "setuptools.build_meta"`: `build-backend`: The Python function that does the build: setuptools' standard entry point. Here: `"setuptools.build_meta"`.

**Lines 5 to 16**

```toml
[project]
name = "azure-service-bus-worker"
version = "0.1.0"
description = "An Azure Service Bus order worker that shows duplicates from lock expiry, per-customer ordering with sessions and poison messages on purpose, with its dead-letter replay tool and the Azure infrastructure as Terraform."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Sumit Srivastava" }]
dependencies = [
    "azure-identity>=1.19,<2",
    "azure-servicebus>=7.13,<8",
]
```

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

- `[project]`: Starts the table `project`: The project's identity and what it needs: name, version, description, supported Python and dependencies. Pip, uv and every other tool read this table.
- `name = "azure-service-bus-worker"`: `name`: The package name, as pip knows it. Here: `"azure-service-bus-worker"`.
- `version = "0.1.0"`: `version`: The version number of the project (`major.minor.patch`). Here: `"0.1.0"`.
- `description = "An Azure Service Bus order worker that shows duplicates from lock expiry, per-customer ordering`: `description`: A one-sentence description shown by tools such as pip. Here: `"An Azure Service Bus order worker that shows duplicates from lock expiry, per-customer ordering with sessions and poison messages on purpose, with its dead-letter replay tool and the Azure infrastructure as Terraform."`.
- `readme = "README.md"`: `readme`: The file that serves as the long description. Here: `"README.md"`.
- `requires-python = ">=3.12"`: `requires-python`: The Python versions the project works with. `>=3.12` means 3.12 or newer. Here: `">=3.12"`.
- `license = { text = "MIT" }`: `license`: The license, here the MIT text. Here: `{ text = "MIT" }`.
- `authors = [{ name = "Sumit Srivastava" }]`: `authors`: Who wrote it. Here: `[{ name = "Sumit Srivastava" }]`.
- `dependencies = [`: `dependencies`: The libraries needed to run the program, each with an allowed version range. The list follows, one item per line.
- `"azure-identity>=1.19,<2",`: `azure-identity>=1.19,<2`: Microsoft's library for obtaining Azure access tokens (managed identity, developer sign-in); version 1.19 or newer and older than 2.
- `"azure-servicebus>=7.13,<8",`: `azure-servicebus>=7.13,<8`: the client library for Azure Service Bus; version 7.13 or newer and older than 8.

**Lines 18 to 26**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "pytest-cov>=5",
    "ruff>=0.6",
    "mypy>=1.11",
    "import-linter>=2.0",
    "pip-audit>=2.7",
]
```

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** **Code coverage** measures which lines (and branches) of the program were run while the tests ran. A line the tests never reach is untested, so the project requires a high percentage for its core layers.

- `[project.optional-dependencies]`: Starts the table `project.optional-dependencies`: Extra sets of dependencies that are installed only when asked for, such as `pip install .[dev]`.
- `dev = [`: `dev`: The tools needed to develop and check the project (tests, linters, security audit). A deployed image does not need them. The list follows, one item per line.
- `"pytest>=8,<10",`: `pytest>=8,<10`: the test runner; version 8 or newer and older than 10.
- `"pytest-cov>=5",`: `pytest-cov>=5`: the pytest plug-in that runs coverage; version 5 or newer.
- `"ruff>=0.6",`: `ruff>=0.6`: the linter and formatter; version 0.6 or newer.
- `"mypy>=1.11",`: `mypy>=1.11`: the type checker; version 1.11 or newer.
- `"import-linter>=2.0",`: `import-linter>=2.0`: the checker of import rules between layers; version 2.0 or newer.
- `"pip-audit>=2.7",`: `pip-audit>=2.7`: the scanner that compares the installed libraries with the database of known security problems; version 2.7 or newer.

**Lines 28 to 33**

```toml
[project.scripts]
order-produce = "order_worker.interfaces.produce_cli:main"
order-worker = "order_worker.interfaces.worker_cli:main"
order-dlq = "order_worker.interfaces.dlq_cli:main"
order-check = "order_worker.interfaces.check_cli:main"
order-simulate = "order_worker.interfaces.simulate_cli:main"
```

- `[project.scripts]`: Starts the table `project.scripts`: Command-line programs the installation creates. Each line maps a command name to a Python function.
- `order-produce = "order_worker.interfaces.produce_cli:main"`: Creates the command `order-produce`. Running it calls the function `main` in the module `order_worker.interfaces.produce_cli`.
- `order-worker = "order_worker.interfaces.worker_cli:main"`: Creates the command `order-worker`. Running it calls the function `main` in the module `order_worker.interfaces.worker_cli`.
- `order-dlq = "order_worker.interfaces.dlq_cli:main"`: Creates the command `order-dlq`. Running it calls the function `main` in the module `order_worker.interfaces.dlq_cli`.
- `order-check = "order_worker.interfaces.check_cli:main"`: Creates the command `order-check`. Running it calls the function `main` in the module `order_worker.interfaces.check_cli`.
- `order-simulate = "order_worker.interfaces.simulate_cli:main"`: Creates the command `order-simulate`. Running it calls the function `main` in the module `order_worker.interfaces.simulate_cli`.

**Lines 35 to 36**

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

- `[tool.setuptools.packages.find]`: Starts the table `tool.setuptools.packages.find`: Tells setuptools (the build tool) where to look for the Python packages to include.
- `where = ["src"]`: `where`: The folders to search for packages: `src`. Keeping code under `src/` makes sure tests import the installed package, not a stray folder. Here: `["src"]`.

**Lines 38 to 41**

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]
```

- `[tool.ruff]`: Starts the table `tool.ruff`: Settings for ruff, the linter and formatter.
- `line-length = 120`: `line-length`: The longest allowed line, 120 characters. Here: `120`.
- `target-version = "py312"`: `target-version`: The oldest Python version the code must work with, so ruff does not suggest newer syntax than that. Here: `"py312"`.
- `src = ["src", "tests"]`: `src`: The folders that contain the project's own code, so ruff can tell project imports from library imports when sorting them. Here: `["src", "tests"]`.

**Lines 43 to 44**

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "D100", "D101", "D103", "D104"]
```

- `[tool.ruff.lint]`: Starts the table `tool.ruff.lint`: Which lint rules ruff applies.
- `select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "D100", "D101", "D103", "D104"]`: `select`: The rule families to switch on (explained one by one below). The families, one by one: `E`: style errors from pycodestyle (line length, spacing, blank lines); `F`: pyflakes, which finds unused imports, unused variables and undefined names; `I`: isort, which keeps imports sorted and grouped; `B`: bugbear, which finds likely bugs (for example a mutable default argument); `UP`: pyupgrade, which suggests modern syntax for the chosen Python version; `SIM`: simplify, which suggests shorter equivalent code; `N`: pep8-naming, which checks the naming conventions (classes in CapWords, functions in lower_case); `C4`: comprehensions, which suggests list and dict comprehensions where they read better; `RUF`: rules specific to ruff; `PT`: pytest style, which checks test conventions; `D100`: every module needs a docstring; `D101`: every public class needs a docstring; `D103`: every public function needs a docstring; `D104`: every package needs a docstring.

**Lines 46 to 47**

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D"]
```

- `[tool.ruff.lint.per-file-ignores]`: Starts the table `tool.ruff.lint.per-file-ignores`: Rules switched off for particular files.
- `"tests/**" = ["D"]`: `"tests/**"`: For every file under `tests/`, ignore the `D` rules (missing docstrings). Test function names already describe the behavior. Here: `["D"]`.

**Lines 49 to 52**

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests"]
```

- `[tool.mypy]`: Starts the table `tool.mypy`: Settings for mypy, the type checker.
- `python_version = "3.12"`: `python_version`: The Python version mypy assumes. Here: `"3.12"`.
- `strict = true`: `strict`: Switches on all of mypy's strict checks, such as requiring a type hint on every function. Here: `true`.
- `files = ["src", "tests"]`: `files`: The folders to check. Here: `["src", "tests"]`.

**Lines 54 to 59**

```toml
# Test functions are named for the behavior they check; annotating every one adds noise, not safety.
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```

- `# Test functions are named for the behavior they check; annotating every one adds noise, not safety.`: Comment for the reader: Test functions are named for the behavior they check; annotating every one adds noise, not safety.
- `[[tool.mypy.overrides]]`: Starts the table `tool.mypy.overrides`: Settings for mypy that apply only to some modules. The double brackets mean this table can appear several times, one per override.
- `module = ["tests.*"]`: `module`: The modules this override applies to (`tests.*` means every module in the tests package). Here: `["tests.*"]`.
- `disallow_untyped_defs = false`: `disallow_untyped_defs`: Whether functions without type hints are an error. `false` allows them for tests. Here: `false`.
- `disallow_incomplete_defs = false`: `disallow_incomplete_defs`: Whether functions with only some hints are an error. `false` allows them for tests. Here: `false`.
- `disallow_untyped_calls = false`: `disallow_untyped_calls`: Whether calling an unhinted function is an error. `false` allows it for tests. Here: `false`.

**Lines 61 to 68**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: the real SQLite ledger on disk, concurrent processes included",
    "e2e: the lesson's three failures through the command-line programs on the simulated broker",
    "azure: needs a deployed Service Bus namespace and an `az login` session (make test-azure)",
]
```

**New idea.** A **process** is one running copy of a program. The operating system gives it its own memory and a number, its *pid*. Two processes do not share variables; they cooperate through files, network connections or signals.

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

- `[tool.pytest.ini_options]`: Starts the table `tool.pytest.ini_options`: Settings for pytest, the test runner.
- `testpaths = ["tests"]`: `testpaths`: Where pytest looks for tests when run without arguments. Here: `["tests"]`.
- `addopts = "-ra --strict-markers"`: `addopts`: Options added to every pytest run: `-ra` prints a summary of why tests were skipped or failed, and `--strict-markers` makes an unknown marker an error, which catches typos. Here: `"-ra --strict-markers"`.
- `markers = [`: `markers`: The markers (labels) tests may carry, each with a description. A run can select them: for example `pytest -m integration`. The list follows, one item per line.
- `"integration: the real SQLite ledger on disk, concurrent processes included",`: the marker `integration`: the real SQLite ledger on disk, concurrent processes included
- `"e2e: the lesson's three failures through the command-line programs on the simulated broker",`: the marker `e2e`: the lesson's three failures through the command-line programs on the simulated broker
- `"azure: needs a deployed Service Bus namespace and an `az login` session (make test-azure)",`: the marker `azure`: needs a deployed Service Bus namespace and an `az login` session (make test-azure)

**Lines 70 to 72**

```toml
[tool.coverage.run]
source = ["order_worker"]
branch = true
```

- `[tool.coverage.run]`: Starts the table `tool.coverage.run`: Settings for how coverage measures which lines the tests ran.
- `source = ["order_worker"]`: `source`: The package whose lines coverage measures. Here: `["order_worker"]`.
- `branch = true`: `branch`: `true` also measures branches (both outcomes of each `if`), not only lines. Here: `true`.

**Lines 74 to 76**

```toml
[tool.coverage.report]
show_missing = true
skip_covered = false
```

- `[tool.coverage.report]`: Starts the table `tool.coverage.report`: Settings for how coverage prints its report.
- `show_missing = true`: `show_missing`: Print the numbers of the lines the tests never ran. Here: `true`.
- `skip_covered = false`: `skip_covered`: `false` also lists files that are fully covered. Here: `false`.

**Lines 78 to 80**

```toml
[tool.importlinter]
root_package = "order_worker"
include_external_packages = true
```

- `[tool.importlinter]`: Starts the table `tool.importlinter`: Settings for import-linter, which checks which module may import which.
- `root_package = "order_worker"`: `root_package`: The top-level package whose imports are checked. Here: `"order_worker"`.
- `include_external_packages = true`: `include_external_packages`: Also check imports of outside libraries, so a rule can forbid `azure` or `flask`. Here: `true`.

**Lines 82 to 90**

```toml
[[tool.importlinter.contracts]]
name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"
type = "layers"
layers = [
    "order_worker.interfaces",
    "order_worker.infrastructure",
    "order_worker.application",
    "order_worker.domain",
]
```

- `[[tool.importlinter.contracts]]`: Starts the table `tool.importlinter.contracts`: One rule (a *contract*) that the import graph must obey. The double brackets mean the table is repeated, one per rule.
- `name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"`: `name`: The rule's name, shown in the report. Here: `"Layers: interfaces -> infrastructure -> application -> domain, never upward"`.
- `type = "layers"`: `type`: The kind of rule: `layers` (a stack where upper layers may import lower layers but not the reverse) or `forbidden` (some modules must not import others). Here: `"layers"`.
- `layers = [`: `layers`: The layers, from the top to the bottom. A module may import only from layers below it. The list follows, one item per line.
- `"order_worker.interfaces",`: layer `order_worker.interfaces`
- `"order_worker.infrastructure",`: layer `order_worker.infrastructure`
- `"order_worker.application",`: layer `order_worker.application`
- `"order_worker.domain",`: layer `order_worker.domain`

**Lines 92 to 96**

```toml
[[tool.importlinter.contracts]]
name = "Domain and application know nothing about Azure or SQLite"
type = "forbidden"
source_modules = ["order_worker.domain", "order_worker.application"]
forbidden_modules = ["azure", "sqlite3"]
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

- `[[tool.importlinter.contracts]]`: Starts the table `tool.importlinter.contracts`: One rule (a *contract*) that the import graph must obey. The double brackets mean the table is repeated, one per rule.
- `name = "Domain and application know nothing about Azure or SQLite"`: `name`: The rule's name, shown in the report. Here: `"Domain and application know nothing about Azure or SQLite"`.
- `type = "forbidden"`: `type`: The kind of rule: `layers` (a stack where upper layers may import lower layers but not the reverse) or `forbidden` (some modules must not import others). Here: `"forbidden"`.
- `source_modules = ["order_worker.domain", "order_worker.application"]`: `source_modules`: The modules the rule restricts. Here: `["order_worker.domain", "order_worker.application"]`.
- `forbidden_modules = ["azure", "sqlite3"]`: `forbidden_modules`: The modules they must not import. Here: `["azure", "sqlite3"]`.

**Lines 98 to 103**

```toml
[[tool.importlinter.contracts]]
name = "Only the infrastructure layer imports the Azure SDK"
type = "forbidden"
source_modules = ["order_worker.interfaces"]
forbidden_modules = ["azure"]
allow_indirect_imports = true
```

**New idea.** An **SDK** (software development kit) or *client library* is a package of ready-made code that talks to a service for you. The Azure ones turn calls such as "read this secret" into the correct web requests, add the access token and retry transient failures.

- `[[tool.importlinter.contracts]]`: Starts the table `tool.importlinter.contracts`: One rule (a *contract*) that the import graph must obey. The double brackets mean the table is repeated, one per rule.
- `name = "Only the infrastructure layer imports the Azure SDK"`: `name`: The rule's name, shown in the report. Here: `"Only the infrastructure layer imports the Azure SDK"`.
- `type = "forbidden"`: `type`: The kind of rule: `layers` (a stack where upper layers may import lower layers but not the reverse) or `forbidden` (some modules must not import others). Here: `"forbidden"`.
- `source_modules = ["order_worker.interfaces"]`: `source_modules`: The modules the rule restricts. Here: `["order_worker.interfaces"]`.
- `forbidden_modules = ["azure"]`: `forbidden_modules`: The modules they must not import. Here: `["azure"]`.
- `allow_indirect_imports = true`: `allow_indirect_imports`: `true` forbids only direct imports, not chains of imports through other modules (so `interfaces` may import infrastructure code that itself imports Azure). Here: `true`.

## Try it yourself

Parse the file with Python's built-in TOML reader.

```bash
.venv/bin/python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(d['project']['name'], d['project']['requires-python']); print(sorted(d['tool']))"
```

You should see something like this:

```text
azure-service-bus-worker >=3.12
['coverage', 'importlinter', 'mypy', 'pytest', 'ruff', 'setuptools']
```

Count the entries of the double-bracket list.

```bash
.venv/bin/python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(len(d['tool']['importlinter']['contracts']), 'contracts')"
```

You should see something like this:

```text
3 contracts
```

## Mistakes people make

- Putting a table twice. TOML forbids defining the same table in two places.
- Quoting numbers or forgetting quotes on strings (`version = 3.1` is a number, not a string).
- Mixing tool settings across files (`setup.cfg`, `mypy.ini`). Here everything is in this one file.
- Loose dependency ranges without a lock file. The lock file is generated from these ranges.
- Forgetting `requires-python`; installers then try the project on versions it does not support.

## Check yourself

1. **What is TOML?**
   Answer: A plain-text configuration format of `key = value` lines grouped in `[tables]`.

2. **What does `[[tool.importlinter.contracts]]` mean?**
   Answer: Another entry in a list of contract tables; the double brackets add one item.

3. **Where does the project name live?**
   Answer: In the `[project]` table.

4. **What does `[build-system]` do?**
   Answer: It names the tool that builds an installable package (setuptools here).

5. **Why have one file for all tools?**
   Answer: One place to read and review the project's settings.

## Further reading

- TOML 1.0: https://toml.io/en/v1.0.0
- pyproject.toml guide: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
