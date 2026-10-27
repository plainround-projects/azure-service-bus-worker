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
