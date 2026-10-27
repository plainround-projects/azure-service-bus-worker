# import-linter

*Fails the build when a layer imports something it must not. Pinned here: import-linter 2.15 (with grimp 3.18).*

## What it is

import-linter is a tool that checks which parts of a Python project are allowed to import which other parts. You write the rules in the configuration, and the tool builds a graph of every `import` in the code and fails if a rule is broken. It is how a layered design stays layered.

## Why this repository uses it

The design is layered, and two outside systems must stay at the edge: the Azure SDK and SQLite. A written rule drifts; a failing check does not.

## Where it appears

| File | What it does with it |
|---|---|
| `pyproject.toml` | `[tool.importlinter]` and the three contracts. |
| `Makefile` | `make lint` runs `lint-imports`. |

## How it works underneath

The tool (using a library called grimp) reads the source files, finds every import statement and builds a directed graph: an arrow from the importing module to the imported one. A **contract** is a rule about that graph.

A `layers` contract lists packages from highest to lowest. A higher layer may import a lower one; a lower layer must never import a higher one. A `forbidden` contract says that one set of modules must not import another set, directly or (unless `allow_indirect_imports = true`) through a chain of other modules.

`lint-imports` reads `[tool.importlinter]` from `pyproject.toml`, runs each contract, and exits non-zero if any is broken.

## Walkthrough of this repository's use

```toml
[tool.importlinter]
root_package = "order_worker"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"
type = "layers"
layers = [
    "order_worker.interfaces",
    "order_worker.infrastructure",
    "order_worker.application",
    "order_worker.domain",
]

[[tool.importlinter.contracts]]
name = "Domain and application know nothing about Azure or SQLite"
type = "forbidden"
source_modules = ["order_worker.domain", "order_worker.application"]
forbidden_modules = ["azure", "sqlite3"]

[[tool.importlinter.contracts]]
name = "Only the infrastructure layer imports the Azure SDK"
type = "forbidden"
source_modules = ["order_worker.interfaces"]
forbidden_modules = ["azure"]
allow_indirect_imports = true
```

The first contract is `type = "layers"`, listed from the top: `interfaces`, `infrastructure`, `application`, `domain`. A higher layer may import a lower one; a lower one must never import a higher one. The second contract, `forbidden`, says `domain` and `application` may not import `azure` or `sqlite3`: the rules and the use cases know nothing about the broker or the database, which is what lets the simulated broker and the tests replace them. The third forbids `interfaces` from importing `azure` directly. It has `allow_indirect_imports = true` because the interfaces layer reaches the SDK through the infrastructure layer on purpose.

### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `pyproject.toml` | 24, 78, 82, 92, 98 | [pyproject-toml.md](pyproject-toml.md) |
| `Makefile` | 67, 71 | [make.md](make.md) |

## Try it yourself

Check the three contracts.

```bash
.venv/bin/lint-imports
```

You should see something like this:

```text
╔══╗─────────▶╔╗ ╔╗      ╔╗◀───┐
╚╣╠╝◀─────┐  ╔╝╚╗║║────▶╔╝╚╗   │
 ║║   ╔══╦══╦╩╗╔╝║║  ╔╦═╩╗╔╝╔═╦══╗
 ║║╔══╣╔╗║╔╗║╔╣║ ║║ ╔╬╣╔╗║║ ║│║╔═╝
╔╣╠╣║║║╚╝║╚╝║║║╚╗║╚═╝║║║║║╚╗║═╣║
╚══╩╩╩╣╔═╩══╩╝╚═╝╚═══╩╩╝╚╩═╩╩═╩╝
  └──▶║║                    ▲
      ╚╝────────────────────┘


---------
Contracts
---------

...
Contracts: 3 kept, 0 broken.
```

See which files import the two outside systems; they are all in `infrastructure/`.

```bash
grep -rn '^import sqlite3\|^from azure' src | cut -d: -f1 | sort -u
```

You should see something like this:

```text
src/order_worker/infrastructure/servicebus.py
src/order_worker/infrastructure/sqlite_ledger.py
src/order_worker/infrastructure/wiring.py
```

## Mistakes people make

- Writing the layers in the wrong order. The first line is the top: nothing may import it.
- Forgetting that `forbidden` also forbids indirect imports unless you allow them; the first version of a contract here failed for exactly that reason.
- Adding an exception to make a violation pass instead of moving the code to the right layer.
- Not running it in CI. Here it is part of `make lint`.
- Expecting it to check third-party packages. It checks them only when `include_external_packages = true`.

## Check yourself

1. **What does a layers contract say?**
   Answer: Packages are listed top to bottom; a package may import those below it and never those above.

2. **What is an indirect import?**
   Answer: An import that reaches a module through a chain of other modules (A imports B, B imports C: A reaches C indirectly).

3. **Why is this check useful?**
   Answer: It makes the architecture a rule that fails the build, not a drawing that drifts.

4. **Where are the contracts written?**
   Answer: In `pyproject.toml` under `[tool.importlinter]`.

5. **What command runs the check?**
   Answer: `lint-imports`, which `make lint` calls.

## Further reading

- import-linter 2.15: https://import-linter.readthedocs.io/en/stable/
- Contract types: https://import-linter.readthedocs.io/en/stable/contract_types.html
