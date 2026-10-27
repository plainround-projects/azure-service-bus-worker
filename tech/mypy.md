# mypy

*Checks the type hints across the source and the tests. Pinned here: mypy 2.4.0.*

## What it is

mypy is a **static type checker** for Python. "Static" means it works on the source text without running the program. It reads the type hints you wrote (`def f(x: int) -> str`) and reports places where the types do not fit, such as passing text where a number is expected.

## Why this repository uses it

Strict typing is part of the repository's quality bar. It catches wrong types in the adapters, including calls into the Azure SDK, before any test runs.

## Where it appears

| File | What it does with it |
|---|---|
| `pyproject.toml` | `[tool.mypy]` and its overrides. |
| `Makefile` | `make lint` runs `mypy`. |

## How it works underneath

mypy builds a model of every function's input and output types from the hints and from the libraries you use. It then walks each function body and checks that every call and assignment is consistent with that model. It reports `file:line: error: message  [code]`.

`strict = true` turns on a bundle of checks: every function must have hints, no untyped calls, and no ignore comments that are no longer needed. A `# type: ignore[code]` comment silences one error; strict mode reports an ignore that is no longer needed.

Some libraries ship **stubs** or inline hints (a `py.typed` marker file) so mypy can check calls into them. Libraries without hints are treated as untyped and need an override.

## Walkthrough of this repository's use

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests"]

# Test functions are named for the behavior they check; annotating every one adds noise, not safety.
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```

`strict = true` switches on the strictest checks. `files = ["src", "tests"]` says what to check, so no path is needed on the command line. The override for `tests.*` relaxes three annotation rules for test functions only (`disallow_untyped_defs`, `disallow_incomplete_defs`, `disallow_untyped_calls`): test names describe the behavior and annotating every function adds noise, not safety. Everything under `src` stays fully annotated.

### What it catches in this code

Return types such as `-> Handled` on the delivery handler, `Delivery | None` on `receive` (a receiver may find nothing), and the `Protocol` ports: if an adapter's method differs from the port's signature, mypy says so even though Python would not. The tests' stubs of the Service Bus SDK carry a few `# type: ignore[...]` comments, each with an error code, where a stub is deliberately not the real class.

## Try it yourself

Run the type checker over source and tests.

```bash
.venv/bin/mypy
```

You should see something like this:

```text
Success: no issues found in 53 source files
```

Check the version.

```bash
.venv/bin/mypy --version
```

You should see something like this:

```text
mypy 2.4.0 (compiled: yes)
```

## Mistakes people make

- Adding `Any` or `# type: ignore` to make errors go away. In this repository ignores are rare and carry an error code.
- Believing mypy proves the program correct. It checks types only, not logic.
- Leaving a function unannotated in strict mode; mypy reports it.
- Forgetting that tests are checked too. The configuration relaxes only the annotation rules for test functions.
- Using `Optional[str]` without handling `None`. mypy flags the missing check.

## Check yourself

1. **What does static mean in static type checker?**
   Answer: It checks the source text without running the program.

2. **What does `strict = true` do?**
   Answer: It enables the strictest bundle of checks, including required annotations on every function.

3. **What is a `py.typed` marker?**
   Answer: An empty file a library ships to tell type checkers that its inline type hints can be trusted.

4. **Does passing mypy mean the program is correct?**
   Answer: No. It means the types are consistent; behavior still needs tests.

5. **What does `# type: ignore[attr-defined]` do?**
   Answer: It silences exactly one kind of error on that line.

## Further reading

- mypy 2.4: https://mypy.readthedocs.io/en/stable/
- Strict mode: https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict
