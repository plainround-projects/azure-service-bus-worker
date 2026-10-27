# ruff

*Checks and formats the Python code on every `make lint`. Pinned here: ruff 0.17.2.*

## What it is

Ruff is a **linter** and a **formatter** for Python, written in Rust so it is very fast. A linter reads source code without running it and reports likely mistakes and style problems. A formatter rewrites the code into one consistent layout (spaces, line breaks, quotes) so that diffs show real changes only.

## Why this repository uses it

The production-grade rule asks for a formatter and a linter in the repository and in CI. Ruff does both and is fast enough to run on every save.

## Where it appears

| File | What it does with it |
|---|---|
| `pyproject.toml` | `[tool.ruff]` settings. |
| `Makefile` | `make lint` runs `ruff check` and `ruff format --check`; `make format` fixes. |
| `.github/workflows/ci.yml` | CI runs `make check`, which includes both. |

## How it works underneath

Ruff reads `[tool.ruff]` in `pyproject.toml`. It parses each `.py` file into a tree and applies **rules**. Each rule has a code: `E501` is "line too long", `F401` is "imported but unused", `I001` is "imports not sorted". `select` lists which families of rules are on.

`ruff check` reports rule violations, and with `--fix` repairs the safe ones. `ruff format` rewrites layout; `ruff format --check` only reports whether any file would change, which is what CI uses. A comment `# noqa: CODE` silences one rule on one line; this repository does not use suppressions to get green.

## Walkthrough of this repository's use

### The settings

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "D100", "D101", "D103", "D104"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D"]
```

`line-length = 120` is the width at which the formatter wraps and the linter complains (`E501`). `target-version = "py312"` tells ruff to assume Python 3.12 features. `src` lists where the project's own packages are, so import sorting can tell them from libraries. `select` turns on rule families: `E` and `F` (errors and pyflakes), `I` (import order), `B` (likely bugs), `UP` (use newer syntax), `SIM` (simplify), `N` (naming), `C4` (comprehensions), `RUF` (ruff's own), `PT` (pytest style), and `D100`, `D101`, `D103`, `D104`, which require a docstring on every module, class, public function and package. The `per-file-ignores` line exempts tests from the docstring rules, because test names already say what they check.

### How `make lint` uses it

```make
lint: $(STAMP) ## ruff, mypy, import-linter, shellcheck, terraform fmt, tflint
```

`ruff check .` runs the linter; `ruff format --check .` only reports files that would change. Neither modifies files. `make format` runs the fixing versions.

## Try it yourself

Check the installed version.

```bash
.venv/bin/ruff --version
```

You should see something like this:

```text
ruff 0.17.2
```

Lint the project.

```bash
.venv/bin/ruff check .
```

You should see something like this:

```text
All checks passed!
```

Check formatting without changing files.

```bash
.venv/bin/ruff format --check .
```

You should see something like this:

```text
75 files already formatted
```

List the rule families ruff knows; `select` in `pyproject.toml` picks some of them.

```bash
.venv/bin/ruff linter | head -8
```

You should see something like this:

```text
AIR Airflow
 ERA eradicate
FAST FastAPI
 YTT flake8-2020
 ANN flake8-annotations
ASYNC flake8-async
   S flake8-bandit
 BLE flake8-blind-except
```

## Mistakes people make

- Silencing a rule with `# noqa` instead of fixing the code. The project's style guide forbids it.
- Running the formatter in CI without `--check`: it would change files that nobody commits.
- Selecting every rule at once and drowning in noise. Rules are chosen on purpose in `pyproject.toml`.
- Mixing formatters. Ruff's formatter is the only one here.
- Forgetting that `--fix` can change behavior for unsafe fixes. Ruff marks those; review them.

## Check yourself

1. **What is the difference between a linter and a formatter?**
   Answer: A linter reports likely mistakes; a formatter only rewrites layout.

2. **What does `ruff format --check` do?**
   Answer: It exits with an error if any file would be reformatted, without changing anything.

3. **What is a rule code such as `E501`?**
   Answer: The name of one check; `E501` means a line is longer than the configured limit.

4. **Where is ruff configured here?**
   Answer: In `pyproject.toml`, under `[tool.ruff]` and `[tool.ruff.lint]`.

5. **Why is the line limit 120 here?**
   Answer: It is set in `line-length = 120`; a team picks one number so the formatter and linter agree.

## Further reading

- Ruff 0.17: https://docs.astral.sh/ruff/
- Rules: https://docs.astral.sh/ruff/rules/
- Configuration: https://docs.astral.sh/ruff/configuration/
