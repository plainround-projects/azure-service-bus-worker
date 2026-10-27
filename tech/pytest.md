# pytest and coverage

*Runs the tests and measures how much code they run. Pinned here: pytest 9.1.1, pytest-cov 7.1.0, coverage 7.17.0.*

## What it is

pytest is a tool that finds and runs the tests of a Python project. A **test** is a function whose name starts with `test_`. It runs some code and uses `assert` to say what must be true. If an `assert` is false, pytest reports a failure and shows both sides of the comparison. **Coverage** (the `pytest-cov` plugin, which uses the `coverage` library) measures which lines of the code the tests ran.

## Why this repository uses it

The lesson's failures depend on time and on several consumers. The tests reproduce each failure deterministically (a fake clock, a simulated broker) and check the fix, without Azure.

## Where it appears

| File | What it does with it |
|---|---|
| `tests/unit/` | Unit tests by layer, with hand-written fakes. |
| `tests/integration/test_sqlite_ledger.py` | The real SQLite file, including four processes. |
| `tests/integration/test_azure_live.py` | Live Azure test, skipped by default. |
| `tests/e2e/test_lesson_scenarios.py` | Each of the lesson's steps through the use cases on the simulated broker. |
| `tests/conftest.py` | Fixtures. |
| `pyproject.toml` | pytest and coverage settings. |
| `Makefile` | `make test`. |

## How it works underneath

pytest walks the folders named in `testpaths`, imports every file called `test_*.py` and collects the functions called `test_*`. For each one it runs the function. A test that raises an exception, or fails an `assert`, is a failure; a test that finishes is a pass.

A **fixture** is a function marked `@pytest.fixture`. When a test lists the fixture's name as a parameter, pytest calls the fixture first and passes in the result. That is how tests get a fresh temporary file or a fake object without repeating code.

A **marker** (`@pytest.mark.something`) labels tests so you can choose them (`-m e2e`). `--strict-markers` makes an unknown label an error, which catches typos.

With `--cov=package`, coverage watches the program while the tests run, records every line and branch that executed, and prints a table of what was missed.

## Walkthrough of this repository's use

### The settings

```toml
[tool.pytest.ini_options]
```

`testpaths` is where pytest looks; `addopts` adds `-ra` (summarize skips and failures) and `--strict-markers`. Three markers are declared: `integration`, `e2e` and `azure`. A test marked `azure` is skipped unless you set `RUN_AZURE_TESTS=1`.

### Hand-written fakes

```python
class FakeDelivery:
    """A delivery that records how it was settled, in order, with the other fakes' events."""

    def __init__(
        self,
        body: bytes,
        message_id: str = "m-1",
        delivery_count: int = 1,
        session_id: str | None = None,
        events: list[str] | None = None,
        lock_lost: bool = False,
        reason: str | None = None,
        description: str | None = None,
    ) -> None:
        self.body = body
        self.message_id = message_id
        self.delivery_count = delivery_count
        self.session_id = session_id
        self.dead_letter_reason = reason
        self.dead_letter_description = description
        self.events = events if events is not None else []
        self.lock_lost = lock_lost
        self.settled: list[str] = []

    def _settle(self, verb: str) -> None:
        if self.lock_lost:
            raise LockLostError("lock lost")
        self.settled.append(verb)
        self.events.append(f"settle:{verb}")

    def complete(self) -> None:
        self._settle("complete")

    def abandon(self) -> None:
```

A **fake** is a small class that stands in for a real dependency and records what happened. `FakeDelivery` records how it was settled and can be told to raise a lost-lock error, which is how the tests check "a lost lock on `complete` is logged, not raised". The shared `events` list lets one test assert the order of calls across several fakes.

### Asserting the order of effects

```python
def test_the_message_is_completed_only_after_the_ledger_write():
    events: list[str] = []
    ledger = FakeLedger(events)
    delivery = FakeDelivery(_command(), events=events)
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert events == ["apply:o-c01-001", "settle:complete"]
    assert (handled.effect, handled.settled) == (Effect.APPLIED, True)
```

The ledger fake and the delivery fake append to the same list, so `events == ["apply:o-c01-001", "settle:complete"]` proves the message is completed only after the write.

### A test that checks the lesson's numbers

```python
def test_step_2_lock_expiry_delivers_one_command_in_ten_twice_and_the_database_shows_the_duplicate_effect(
    database, sql_dir
):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE)
    assert (result.report.rows, result.report.total) == (1100, 11000.0)
    assert result.max_delivery_count == 2
    assert result.stats.lock_lost == 100
    assert len(result.report.duplicate_orders) == 100
```

This runs the real use cases on the simulated broker and a real SQLite file and asserts the lesson's expected output: 1,100 rows and 11,000.0, with a delivery count of 2 and 100 lost locks.

### A real concurrency test

```python
_WORKER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from order_worker.domain.commands import OrderCommand
    from order_worker.infrastructure.sqlite_ledger import SqliteLedger

    ledger = SqliteLedger(Path(sys.argv[1]))
    start, count = int(sys.argv[2]), int(sys.argv[3])
    for n in range(start, start + count):
        customer = f"c{(n % 20) + 1:02d}"
        ledger.apply(f"m-{n}", OrderCommand(f"o-{n}", customer, n // 20 + 1, 1000), 1, deduplicate=True)
    ledger.close()
    """
)
```

Four operating-system processes write to the same database file at once; the test then checks no row was lost or duplicated. `subprocess.Popen([sys.executable, "-c", code, ...])` starts each one.

### Skipping on purpose

```python
pytestmark = [
    pytest.mark.azure,
    pytest.mark.skipif(os.environ.get("RUN_AZURE_TESTS") != "1", reason="set RUN_AZURE_TESTS=1 after deploying"),
]
```

`pytest.mark.skipif(condition, reason=...)` skips every test in the file unless the environment variable is set, and the reason shows in the report.

### The coverage bar

```make
test: $(STAMP) ## unit, integration (real SQLite) and end-to-end (simulated broker) tests with coverage
	$(PY) -m pytest tests/unit tests/integration tests/e2e --cov=order_worker --cov-report=term
	$(PY) -m coverage report --include='src/order_worker/domain/*,src/order_worker/application/*' --fail-under=95
```

Runs unit, integration and end-to-end tests with coverage, then requires 95 percent on `domain` and `application` (they are at 99 to 100).

## Try it yourself

Run the domain tests.

```bash
.venv/bin/python -m pytest tests/unit/domain -q -p no:cacheprovider
```

You should see something like this:

```text
.........................................                                [100%]
41 passed in 0.13s
```

Reproduce the duplicate effect and its fix.

```bash
.venv/bin/python -m pytest tests/e2e -q -p no:cacheprovider -k 'step_2 or step_3_idempotence'
```

You should see something like this:

```text
..                                                                       [100%]
2 passed, 12 deselected in 3.39s
```

Count every test.

```bash
.venv/bin/python -m pytest tests -q -p no:cacheprovider --collect-only -q | tail -2
```

You should see something like this:

```text
tests/unit/interfaces/test_clis.py: 15
```

See the live test skipped, with its reason.

```bash
.venv/bin/python -m pytest tests/integration/test_azure_live.py -q -p no:cacheprovider -rs
```

You should see something like this:

```text
s                                                                        [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/integration/test_azure_live.py:22: set RUN_AZURE_TESTS=1 after deploying
1 skipped in 3.58s
```

## Mistakes people make

- Tests that depend on each other's order or leave files behind. Here every test gets its own temporary folder (`tmp_path`).
- Asserting too little: a test that only checks that nothing crashed. The test names here say the behavior they check.
- Sleeping in tests to wait for time to pass. The code takes a clock as an input and the tests use a fake clock, so no test waits.
- Chasing 100 percent coverage everywhere. This repository sets the bar where it matters (the domain and application layers) and reports the rest.
- Forgetting the marker on slow tests. Slow tests are marked and live in their own folder.

## Check yourself

1. **How does pytest know a function is a test?**
   Answer: Its name starts with `test_` and it is in a file called `test_*.py` under a folder listed in `testpaths`.

2. **What does a fixture give a test?**
   Answer: A prepared value (a temporary folder, a fake) that pytest creates and passes in by parameter name.

3. **What does `--strict-markers` do?**
   Answer: It turns a marker that is not declared in the configuration into an error.

4. **What does coverage measure?**
   Answer: Which lines and branches of the code ran while the tests ran.

5. **Why does this repository inject a clock instead of sleeping?**
   Answer: So tests are fast and give the same answer every time.

## Further reading

- pytest 9.1: https://docs.pytest.org/en/stable/
- pytest-cov 7.1: https://pytest-cov.readthedocs.io/en/latest/
- coverage.py 7.17: https://coverage.readthedocs.io/en/7.17.0/
