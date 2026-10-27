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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `tests/conftest.py`

10 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Shared fixtures."""
```

**New idea.** A **module** is one `.py` file. Python runs a file from the top to the bottom, once, the first time something imports it; `def` and `class` statements at the top level just create functions and classes, they do not run their bodies.

**New idea.** A **docstring** is a text in triple quotes as the very first statement of a module, class or function. It does nothing when the program runs; tools and people read it as the official description.

The module docstring says: Shared fixtures.

**Line 3**

```python
from pathlib import Path
```

What happens, step by step:

- `Path` from `pathlib`: a file path as an object.

**Line 5**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Line 7**

```python
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
```

**New idea.** **DNS** (the Domain Name System) is the network's telephone book: it turns a name such as `myvault.vault.azure.net` into the IP address a computer connects to. Asking it is called *resolving* the name, and the answer depends on which network and which name server you ask.

**New idea.** `pathlib.Path` represents a file path as an object: `Path("a") / "b"` joins parts, `.read_text()` reads a file, `.exists()` tests for it.

What happens, step by step:

- Sets `SQL_DIR` to `Path(__file__).resolve().parents[1] / 'sql'`.

Names used here:

- `Path.resolve()` turns a path into an absolute one.
- `Path(text)` represents a file path.

**Lines 10 to 12**

```python
@pytest.fixture
def sql_dir() -> Path:
    return SQL_DIR
```

**Function `sql_dir`** takes no parameters; gives back `Path`.

**New idea.** A **type hint** such as `name: str` or `-> int` says what kind of value a parameter or result is. Python does not enforce hints when the program runs; the checker `mypy` reads them before the program runs and reports mismatches.

**New idea.** A **fixture** is a helper function marked `@pytest.fixture`. When a test lists the fixture's name as a parameter, pytest runs the fixture first and passes in what it returns. A fixture with `yield` hands the value to the test, then runs the code after the `yield` as clean-up once the test ends.

**New idea.** `def name(parameters):` defines a **function**: a named, reusable block of code. The indented lines under it are its body, which runs only when the function is **called** as `name(values)`. `return value` hands a result back to the caller; a function without `return` gives back `None`.

What happens, step by step:

- Decorator `@pytest.fixture`.
- Returns `SQL_DIR`.

**Lines 15 to 17**

```python
@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "orders.db"
```

**Function `database`** takes `tmp_path` (type `Path`); gives back `Path`.

**New idea.** `tmp_path` is a built-in pytest fixture giving each test its own empty temporary folder (as a `Path`), deleted later, so tests never share files.

What happens, step by step:

- Decorator `@pytest.fixture`.
- Returns `tmp_path / 'orders.db'`.

#### `tests/e2e/test_lesson_scenarios.py`

125 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The lesson's checks, one test each, on the simulated broker and a real SQLite ledger."""
```

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

The module docstring says: The lesson's checks, one test each, on the simulated broker and a real SQLite ledger.

**Lines 3 to 5**

```python
import json
import subprocess
import sys
```

What happens, step by step:

- `json`: the standard-library module for JSON.
- `subprocess`: the standard-library module for starting other programs.
- `sys`: the standard-library module for the running interpreter (arguments, exit, streams).

**Line 7**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 9 to 17**

```python
from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.ports import OutgoingMessage
from order_worker.application.run_worker import RunWorker
from order_worker.domain.commands import parse_command
from order_worker.domain.errors import TransientError
from order_worker.domain.processing import ApplyResult, Mode
from order_worker.infrastructure.scenarios import run_duplicates, run_ordering, run_poison_and_replay
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

**New idea.** A **transaction** groups several database changes so that they all happen or none does. `COMMIT` makes them permanent; `ROLLBACK` throws them away. Another reader never sees a half-finished transaction.

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

**New idea.** An Azure **budget** watches the spending of a subscription and e-mails people when it passes a threshold such as 80 or 100 percent. It alerts; it does not stop anything from running.

What happens, step by step:

- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `RunWorker` from the repository's own module `order_worker.application.run_worker`: Receive until told to stop, until idle for a while, or until a message budget is spent (defined in `src/order_worker/application/run_worker.py`)
- `parse_command` from the repository's own module `order_worker.domain.commands`: Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show (defined in `src/order_worker/domain/commands.py`)
- `TransientError` from the repository's own module `order_worker.domain.errors`: A failure that a retry may fix (a busy database): the message is abandoned and delivered again (defined in `src/order_worker/domain/errors.py`)
- `ApplyResult` from the repository's own module `order_worker.domain.processing`: What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write (defined in `src/order_worker/domain/processing.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `run_duplicates` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson steps 1 to 3: one worker, a 30-second lock, every `slow_every`-th command takes 45 seconds (defined in `src/order_worker/infrastructure/scenarios.py`)
- `run_ordering` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson step 4: several workers on one queue, one of them stalls on a command of customer c01 (defined in `src/order_worker/infrastructure/scenarios.py`)
- `run_poison_and_replay` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson steps 5 and 6: the poison command is dead-lettered with a reason, then fixed and replayed (defined in `src/order_worker/infrastructure/scenarios.py`)
- `ManualClock` from the repository's own module `order_worker.infrastructure.simulation`: Time that moves only when someone sleeps (defined in `src/order_worker/infrastructure/simulation.py`)
- `SimulatedBroker` from the repository's own module `order_worker.infrastructure.simulation`: One queue and its dead-letter sub-queue (defined in `src/order_worker/infrastructure/simulation.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `prepare_database` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql` (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)

**Line 19**

```python
pytestmark = pytest.mark.e2e
```

What happens, step by step:

- Sets `pytestmark` to `pytest.mark.e2e`.

**Lines 22 to 25**

```python
def test_step_1_a_thousand_commands_end_up_in_the_database_exactly_as_expected(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE, slow_every=0)
    assert (result.report.rows, result.report.total) == (1000, 10000.0)
    assert result.problems == []
```

**Function `test_step_1_a_thousand_commands_end_up_in_the_database_exactly_as_expected`** takes `database`, `sql_dir`.

**New idea.** A **test function** is a function whose name starts with `test_`. pytest finds it by that name, calls it, and reports a pass if it returns normally and a failure if an `assert` fails or an error is raised.

**New idea.** `assert condition` checks that a condition is true. If it is false, the program stops with an `AssertionError`. Test code uses it to state expectations; pytest shows both sides of a failed comparison.

**New idea.** A **tuple** `(a, b)` is a fixed list of values. **Unpacking** `x, y = pair` assigns the parts to separate names in one statement.

What happens, step by step:

- Sets `result` to the result of calling `run_duplicates(database, sql_dir, mode=Mode.NAIVE, slow_every=0)`.
- Checks that `(result.report.rows, result.report.total)` equals `(1000, 10000.0)`.
- Checks that `result.problems` equals `[]`.

**Lines 28 to 36**

```python
def test_step_2_lock_expiry_delivers_one_command_in_ten_twice_and_the_database_shows_the_duplicate_effect(
    database, sql_dir
):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE)
    assert (result.report.rows, result.report.total) == (1100, 11000.0)
    assert result.max_delivery_count == 2
    assert result.stats.lock_lost == 100
    assert len(result.report.duplicate_orders) == 100
    assert "duplicate effect for order o-c01-010" in result.problems
```

**Function `test_step_2_lock_expiry_delivers_one_command_in_ten_twice_and_the_database_shows_the_duplicate_effect`** takes `database`, `sql_dir`.

**New idea.** `a in b` is true when `a` is one of the items of `b` (or a piece of the text `b`).

What happens, step by step:

- Sets `result` to the result of calling `run_duplicates(database, sql_dir, mode=Mode.NAIVE)`.
- Checks that `(result.report.rows, result.report.total)` equals `(1100, 11000.0)`.
- Checks that `result.max_delivery_count` equals `2`.
- Checks that `result.stats.lock_lost` equals `100`.
- Checks that `len(result.report.duplicate_orders)` equals `100`.
- Checks that `'duplicate effect for order o-c01-010'` is one of / is inside `result.problems`.

Names used here:

- `len(x)` counts the items in `x`.

**Lines 39 to 42**

```python
def test_step_3_idempotence_alone_removes_the_duplicate_effect_but_not_the_lost_locks(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT)
    assert result.problems == []
    assert (result.stats.skipped_duplicates, result.stats.lock_lost) == (100, 100)
```

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

**Function `test_step_3_idempotence_alone_removes_the_duplicate_effect_but_not_the_lost_locks`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT)`.
- Checks that `result.problems` equals `[]`.
- Checks that `(result.stats.skipped_duplicates, result.stats.lock_lost)` equals `(100, 100)`.

**Lines 45 to 48**

```python
def test_step_3_lock_renewal_alone_prevents_the_redelivery_in_this_run(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE, lock_renewal_seconds=300)
    assert result.problems == []
    assert (result.max_delivery_count, result.stats.lock_lost) == (1, 0)
```

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

**Function `test_step_3_lock_renewal_alone_prevents_the_redelivery_in_this_run`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_duplicates(database, sql_dir, mode=Mode.NAIVE, lock_renewal_seconds=300)`.
- Checks that `result.problems` equals `[]`.
- Checks that `(result.max_delivery_count, result.stats.lock_lost)` equals `(1, 0)`.

**Lines 51 to 54**

```python
def test_step_3_both_together_give_the_clean_run_with_no_lock_errors(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT, lock_renewal_seconds=300)
    assert result.problems == []
    assert (result.stats.skipped_duplicates, result.stats.lock_lost) == (0, 0)
```

**Function `test_step_3_both_together_give_the_clean_run_with_no_lock_errors`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT, lock_renewal_seconds=300)`.
- Checks that `result.problems` equals `[]`.
- Checks that `(result.stats.skipped_duplicates, result.stats.lock_lost)` equals `(0, 0)`.

**Lines 57 to 79**

```python
def test_step_3_a_crash_after_the_commit_is_the_case_only_idempotence_covers(database, sql_dir):
    """Renewal cannot help when the worker dies between the commit and the complete; the redelivery must be harmless."""
    prepare_database(database, sql_dir, with_migrations=True)
    clock = ManualClock()
    broker = SimulatedBroker(clock)
    body = json.dumps({"orderId": "o-1", "customerId": "c01", "seq": 1, "amount": 10.0})
    broker.send([OutgoingMessage(body, "o-1")])
    ledger = SqliteLedger(database)
    try:
        receiver = broker.inbox().open()
        assert receiver is not None
        first = receiver.receive(1)
        assert first is not None
        ledger.apply("o-1", parse_command(first.body), 1, deduplicate=True)
        # ... and the process dies here, before first.complete(): the lock expires and the queue redelivers.
        clock.sleep(31)
        stats = RunWorker(broker.inbox(), HandleDelivery(ledger, clock, Mode.IDEMPOTENT), clock).run(
            until_idle_seconds=5
        )
        assert (stats.applied, stats.skipped_duplicates) == (0, 1)
        assert len(ledger.rows()) == 1
    finally:
        ledger.close()
```

The docstring in the code says: Renewal cannot help when the worker dies between the commit and the complete; the redelivery must be harmless.

**Function `test_step_3_a_crash_after_the_commit_is_the_case_only_idempotence_covers`** takes `database`, `sql_dir`.

**New idea.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up.

**New idea.** **JSON** is a text format for data: objects `{"key": value}`, arrays `[1, 2]`, strings, numbers, `true`, `false` and `null`. `json.dumps(x)` turns Python data into JSON text and `json.loads(text)` turns JSON text back into Python data.

**New idea.** A **dictionary** `{key: value}` looks values up by key: `d[key]` reads one, `d.get(key)` reads one and returns `None` if missing.

**New idea.** `x is None` tests whether `x` is exactly the object `None` (identity), as opposed to `==`, which tests equal value.

**New idea.** `None` is Python's value for "nothing here". Functions that find nothing return it, and a parameter that defaults to `None` means "not given".

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock)`.
- Sets `body` to the result of calling `json.dumps({'orderId': 'o-1', 'customerId': 'c01', 'seq': 1, 'amount': 10.0})`.
- Calls `broker.send([OutgoingMessage(body, 'o-1')])`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Try:
  - Sets `receiver` to the result of calling `broker.inbox().open()`.
  - Checks that `receiver` is not exactly `None`.
  - Sets `first` to the result of calling `receiver.receive(1)`.
  - Checks that `first` is not exactly `None`.
  - Calls `ledger.apply('o-1', parse_command(first.body), 1, deduplicate=True)`.
  - Calls `clock.sleep(31)`.
  - Sets `stats` to the result of calling `RunWorker(broker.inbox(), HandleDelivery(ledger, clock, Mode.IDEMPOTENT), clock).run` with `until_idle_seconds` set to `5`.
  - Checks that `(stats.applied, stats.skipped_duplicates)` equals `(0, 1)`.
  - Checks that `len(ledger.rows())` equals `1`.
- Always, in the end:
  - Calls `ledger.close()`.

Names used here:

- `json.dumps(x)` turns Python data into JSON text.

**Lines 82 to 86**

```python
def test_step_4_without_sessions_a_stalled_worker_lets_a_customers_commands_be_applied_out_of_order(database, sql_dir):
    result = run_ordering(database, sql_dir, sessions=False)
    assert result.report.rows == 1000
    assert result.report.out_of_order, "the check must see the reordering"
    assert any("c01" in line for line in result.report.out_of_order)
```

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

**Function `test_step_4_without_sessions_a_stalled_worker_lets_a_customers_commands_be_applied_out_of_order`** takes `database`, `sql_dir`.

**New idea.** A **generator expression** `(f(x) for x in things)` produces its values one at a time as they are asked for, instead of building the whole list first.

What happens, step by step:

- Sets `result` to the result of calling `run_ordering(database, sql_dir, sessions=False)`.
- Checks that `result.report.rows` equals `1000`.
- Checks that `result.report.out_of_order` is true. If not, the failure message is `'the check must see the reordering'`.
- Checks that `any(('c01' in line for line in result.report.out_of_order))` is true.

Names used here:

- `any(x)` is true if at least one item is true.

**Lines 89 to 92**

```python
def test_step_4_with_sessions_every_customers_commands_apply_in_order_even_with_a_stalled_worker(database, sql_dir):
    result = run_ordering(database, sql_dir, sessions=True)
    assert result.problems == []
    assert result.report.out_of_order == ()
```

**Function `test_step_4_with_sessions_every_customers_commands_apply_in_order_even_with_a_stalled_worker`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_ordering(database, sql_dir, sessions=True)`.
- Checks that `result.problems` equals `[]`.
- Checks that `result.report.out_of_order` equals `()`.

**Lines 95 to 96**

```python
def test_step_4_more_workers_keep_the_order_when_sessions_are_on(database, sql_dir):
    assert run_ordering(database, sql_dir, sessions=True, workers=7, stall_rounds=25).problems == []
```

**Function `test_step_4_more_workers_keep_the_order_when_sessions_are_on`** takes `database`, `sql_dir`.

What happens, step by step:

- Checks that `run_ordering(database, sql_dir, sessions=True, workers=7, stall_rounds=25).problems` equals `[]`.

**Lines 99 to 102**

```python
def test_step_5_the_poison_command_goes_to_the_dead_letter_queue_with_a_reason_and_the_rest_flows(database, sql_dir):
    result = run_poison_and_replay(database, sql_dir)
    assert result.dead_letters_before == [("o-bad", "InvalidAmount", "amount is not a number")]
    assert result.ledger_rows_before == 1000
```

**Function `test_step_5_the_poison_command_goes_to_the_dead_letter_queue_with_a_reason_and_the_rest_flows`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_poison_and_replay(database, sql_dir)`.
- Checks that `result.dead_letters_before` equals `[('o-bad', 'InvalidAmount', 'amount is not a number')]`.
- Checks that `result.ledger_rows_before` equals `1000`.

**Lines 105 to 111**

```python
def test_step_6_the_fixed_command_is_processed_once_even_if_the_tool_runs_twice(database, sql_dir):
    result = run_poison_and_replay(database, sql_dir)
    assert (result.replay.fixed, result.second_replay.fixed) == (1, 0)
    assert result.o_bad_rows == 1
    assert result.after.report.rows == 1001
    assert result.after.problems == []
    assert result.after.dead_letters == []
```

**Function `test_step_6_the_fixed_command_is_processed_once_even_if_the_tool_runs_twice`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_poison_and_replay(database, sql_dir)`.
- Checks that `(result.replay.fixed, result.second_replay.fixed)` equals `(1, 0)`.
- Checks that `result.o_bad_rows` equals `1`.
- Checks that `result.after.report.rows` equals `1001`.
- Checks that `result.after.problems` equals `[]`.
- Checks that `result.after.dead_letters` equals `[]`.

**Lines 114 to 119**

```python
def test_step_6_the_replay_keeps_the_session_so_the_fixed_command_lands_after_the_customers_earlier_ones(
    database, sql_dir
):
    result = run_poison_and_replay(database, sql_dir, sessions=True)
    assert result.o_bad_rows == 1
    assert result.after.problems == []
```

**Function `test_step_6_the_replay_keeps_the_session_so_the_fixed_command_lands_after_the_customers_earlier_ones`** takes `database`, `sql_dir`.

What happens, step by step:

- Sets `result` to the result of calling `run_poison_and_replay(database, sql_dir, sessions=True)`.
- Checks that `result.o_bad_rows` equals `1`.
- Checks that `result.after.problems` equals `[]`.

**Lines 122 to 138**

```python
def test_a_message_that_keeps_failing_is_dead_lettered_by_the_queue_after_the_maximum_deliveries(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    clock = ManualClock()
    broker = SimulatedBroker(clock)
    broker.send([OutgoingMessage(json.dumps({"orderId": "o-1", "customerId": "c01", "seq": 1, "amount": 10.0}), "o-1")])

    class AlwaysBusy(SqliteLedger):
        def apply(self, *args, **kwargs) -> ApplyResult:
            raise TransientError("busy")

    ledger = AlwaysBusy(database)
    try:
        stats = RunWorker(broker.inbox(), HandleDelivery(ledger, clock), clock).run(until_idle_seconds=5)
    finally:
        ledger.close()
    assert stats.abandoned == 10
    assert broker.dead_letter_reasons()[0][:2] == ("o-1", "MaxDeliveryCountExceeded")
```

**Function `test_a_message_that_keeps_failing_is_dead_lettered_by_the_queue_after_the_maximum_deliveries`** takes `database`, `sql_dir`.

**New idea.** `class Child(Parent):` makes `Child` **inherit** from `Parent`: it starts with all of the parent's attributes and methods and can add to or replace them. `super()` reaches the parent's version of a method.

**New idea.** `class Name:` defines a **class**: a blueprint for objects that bundle data (attributes) with functions that work on it (methods). Calling the class, `Name(...)`, builds one object, an **instance**.

**New idea.** `*args` collects extra positional arguments into a tuple, and `**kwargs` collects extra named arguments into a dictionary.

**New idea.** Inside a method, the first parameter, by convention `self`, is the object the method was called on. `self.value` reads or sets an attribute of that object.

**New idea.** `raise Error(...)` stops the current function and signals a failure. `raise NewError(...) from error` also records the original error as the cause, so the traceback shows both.

**New idea.** `items[1:3]` is a **slice**: the elements from position 1 up to (not including) 3. Positions start at 0, and a negative position counts from the end.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock)`.
- Calls `broker.send` with `[OutgoingMessage(json.dumps({'orderId': 'o-1', 'customerId': 'c01', 'seq': 1, 'amount': 10.0}), 'o-1')]`.
- Defines the class `AlwaysBusy`.
- Sets `ledger` to the result of calling `AlwaysBusy(database)`.
- Try:
  - Sets `stats` to the result of calling `RunWorker(broker.inbox(), HandleDelivery(ledger, clock), clock).run(until_idle_seconds=5)`.
- Always, in the end:
  - Calls `ledger.close()`.
- Checks that `stats.abandoned` equals `10`.
- Checks that `broker.dead_letter_reasons()[0][:2]` equals `('o-1', 'MaxDeliveryCountExceeded')`.

Names used here:

- `dead_letter_reasons` is the repository's own: (message id, reason, description) of every dead letter (defined in `src/order_worker/infrastructure/simulation.py`)

**Lines 141 to 159**

```python
def test_the_simulation_program_runs_as_a_separate_process_and_exits_by_expectation():
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "order_worker.interfaces.simulate_cli",
            "--expect",
            "dirty",
            "duplicates",
            "--mode",
            "naive",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "ledger: 1100|11000.0" in run.stdout
```

**New idea.** Every program has **standard output** (its normal results) and **standard error** (its problem reports), two separate streams. Keeping them apart lets a caller capture the results while still seeing the errors.

**New idea.** A **timeout** is the longest a program waits for something before giving up. Without one, a call to a service that never answers would make the program wait forever.

**Function `test_the_simulation_program_runs_as_a_separate_process_and_exits_by_expectation`** takes no parameters.

**New idea.** `subprocess.run([...])` starts another program as a separate **process** (a running program with its own memory) and waits for it; the result holds its exit code and output.

What happens, step by step:

- Sets `run` to the result of calling `subprocess.run` with `[sys.executable, '-m', 'order_worker.interfaces.simulate_cli', '--expect', 'dirty', 'duplicates', '--mode', '…` (long; see the quote); `capture_output` set to `True`; `text` set to `True`; `timeout` set to `300`; `check` set to `False`.
- Checks that `run.returncode` equals `0`. If not, the failure message is `run.stderr`.
- Checks that `'ledger: 1100|11000.0'` is one of / is inside `run.stdout`.

#### `tests/integration/test_azure_live.py`

29 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```python
"""The real Service Bus adapter against a deployed namespace. Skipped unless RUN_AZURE_TESTS=1 and you are signed in.

It uses a throwaway session-less message on the `orders` queue, so run it on an empty queue (before `make produce`).
`make test-azure` after `make up`, with SB_NAMESPACE exported (see docs/RUNBOOK.md).
"""
```

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

The module docstring says: The real Service Bus adapter against a deployed namespace. Skipped unless RUN_AZURE_TESTS=1 and you are signed in. It uses a throwaway session-less message on the `orders` queue, so run it on an empty queue (before `make produce`). `make test-azure` after `make up`, with SB_NAMESPACE exported (see docs/RUNBOOK.md).

**Lines 7 to 8**

```python
import os
import uuid
```

**New idea.** A **GUID** (or UUID) is a 128-bit identifier written as 32 hexadecimal digits in groups, such as `00000000-0000-0000-0000-000000000000`. Azure uses them for subscriptions, tenants and identities. The all-zero value in examples is a placeholder, not a real id.

What happens, step by step:

- `os`: the standard-library module for the operating system (environment variables, files).
- `uuid`: the standard-library module for unique identifiers.

**Line 10**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 12 to 14**

```python
from order_worker.application.ports import OutgoingMessage
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect
```

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `connect` from the repository's own module `order_worker.infrastructure.wiring`: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)

**Lines 16 to 19**

```python
pytestmark = [
    pytest.mark.azure,
    pytest.mark.skipif(os.environ.get("RUN_AZURE_TESTS") != "1", reason="set RUN_AZURE_TESTS=1 after deploying"),
]
```

**New idea.** **Environment variables** are named text values the operating system hands to every program when it starts (for example `PORT=8080`). `os.environ` is a dictionary-like view of them. They are the usual way to configure a program without changing its code, and the usual way to hand it a setting that differs between machines.

What happens, step by step:

- Sets `pytestmark` to `[pytest.mark.azure, pytest.mark.skipif(os.environ.get('RUN_AZURE_TESTS') != '1', reason='set RUN_AZURE_TESTS=…` (long; see the quote).

Names used here:

- `.get(key, default)` on a dictionary reads a value and returns the default (or `None`) when the key is missing.

**Lines 22 to 36**

```python
def test_a_message_sent_with_the_sender_role_is_received_with_the_receiver_role_and_completed():
    settings = Settings.from_env({**os.environ, "USE_SESSIONS": "", "SB_QUEUE": os.environ.get("SB_QUEUE", "orders")})
    message_id = f"live-{uuid.uuid4().hex[:8]}"
    with connect(settings) as messaging:
        messaging.sender().send([OutgoingMessage("live test", message_id)])
        receiver = messaging.inbox(sessions=False, max_wait_seconds=20, lock_renewal_seconds=0).open()
        assert receiver is not None
        try:
            delivery = receiver.receive(20)
            assert delivery is not None
            assert delivery.message_id == message_id
            assert delivery.delivery_count == 1
            delivery.complete()
        finally:
            receiver.close()
```

**Function `test_a_message_sent_with_the_sender_role_is_received_with_the_receiver_role_and_completed`** takes no parameters.

**New idea.** A `with` block uses a **context manager**: an object that does set-up when the block starts and clean-up when it ends, even if an error happens in between (for example, closing a file or releasing a lock). `with x as y:` runs the block with the set-up result in `y`.

**New idea.** An **f-string** is text written `f"...{value}..."`: whatever is inside the braces is evaluated and its text is put into the string. A format after a colon controls how: `{x:g}` prints a number without trailing zeros, `{x:.1f}` keeps one decimal, `{x!r}` uses the value's `repr`.

What happens, step by step:

- Sets `settings` to the result of calling `Settings.from_env` with `{**os.environ, 'USE_SESSIONS': '', 'SB_QUEUE': os.environ.get('SB_QUEUE', 'orders')}`.
- Sets `message_id` to `f'live-{uuid.uuid4().hex[:8]}'`.
- Inside a block that `connect(settings)` and call it `messaging`:
  - Calls `messaging.sender().send([OutgoingMessage('live test', message_id)])`.
  - Sets `receiver` to the result of calling `messaging.inbox(sessions=False, max_wait_seconds=20, lock_renewal_seconds=0).open()`.
  - Checks that `receiver` is not exactly `None`.
  - Try:
    - Sets `delivery` to the result of calling `receiver.receive(20)`.
    - Checks that `delivery` is not exactly `None`.
    - Checks that `delivery.message_id` equals `message_id`.
    - Checks that `delivery.delivery_count` equals `1`.
    - Calls `delivery.complete()`.
  - Always, in the end:
    - Calls `receiver.close()`.

Names used here:

- `from_env` is the repository's own: Read and validate `env`; raise `ConfigError` naming every problem at once (defined in `src/order_worker/infrastructure/settings.py`)
- `uuid.uuid4()` creates a random unique identifier.

#### `tests/integration/test_sqlite_ledger.py`

121 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The real SQLite ledger on disk: transactions, the unique key that deduplicates, and several processes at once."""
```

The module docstring says: The real SQLite ledger on disk: transactions, the unique key that deduplicates, and several processes at once.

**Lines 3 to 8**

```python
import sqlite3
import subprocess
import sys
import textwrap
from contextlib import closing
from pathlib import Path
```

What happens, step by step:

- `sqlite3`: the standard-library module for SQLite databases.
- `subprocess`: the standard-library module for starting other programs.
- `sys`: the standard-library module for the running interpreter (arguments, exit, streams).
- `textwrap`: the standard-library module for formatting blocks of text.
- `closing` from `contextlib`: wraps an object so a `with` block calls its `close()` at the end.
- `Path` from `pathlib`: a file path as an object.

**Line 10**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 12 to 14**

```python
from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import TransientError, UnknownCustomerError
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, is_reachable, prepare_database
```

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

What happens, step by step:

- `OrderCommand` from the repository's own module `order_worker.domain.commands`: One order: who ordered, which order, the customer's sequence number and the amount in cents (defined in `src/order_worker/domain/commands.py`)
- `TransientError` from the repository's own module `order_worker.domain.errors`: A failure that a retry may fix (a busy database): the message is abandoned and delivered again (defined in `src/order_worker/domain/errors.py`)
- `UnknownCustomerError` from the repository's own module `order_worker.domain.errors`: The command names a customer that does not exist (defined in `src/order_worker/domain/errors.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `is_reachable` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: True when the ledger file opens and answers a query (used by the readiness probe) (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `prepare_database` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql` (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)

**Line 16**

```python
pytestmark = pytest.mark.integration
```

What happens, step by step:

- Sets `pytestmark` to `pytest.mark.integration`.

**Lines 19 to 20**

```python
def _command(n: int, customer: str = "c01") -> OrderCommand:
    return OrderCommand(f"o-{customer}-{n:03d}", customer, n, 1000)
```

**Function `_command`** takes `n` (type `int`), `customer` (type `str`), default `'c01'`; gives back `OrderCommand`.

**New idea.** A parameter written `name=value` has a **default**: if the caller leaves it out, the default is used.

What happens, step by step:

- Returns `OrderCommand(f'o-{customer}-{n:03d}', customer, n, 1000)`.

**Lines 23 to 28**

```python
@pytest.fixture
def ledger(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    instance = SqliteLedger(database)
    yield instance
    instance.close()
```

**Function `ledger`** takes `database`, `sql_dir`.

**New idea.** `yield value` makes a function a **generator**: instead of returning once, it hands out one value at a time and pauses until the next one is asked for.

What happens, step by step:

- Decorator `@pytest.fixture`.
- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `instance` to the result of calling `SqliteLedger(database)`.
- Evaluates `(yield instance)`.
- Calls `instance.close()`.

**Lines 31 to 37**

```python
def test_preparing_the_database_twice_is_harmless_and_seeds_twenty_customers(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    prepare_database(database, sql_dir, with_migrations=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone() == (20,)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"customers", "ledger", "processed_messages"} <= tables
```

**Function `test_preparing_the_database_twice_is_harmless_and_seeds_twenty_customers`** takes `database`, `sql_dir`.

**New idea.** A **comprehension** builds a list, set or dictionary in one expression: `[f(x) for x in things if keep(x)]` means "for each `x` in `things` that passes `keep`, take `f(x)`". With braces and `key: value` it builds a dictionary.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Inside a block that `closing(sqlite3.connect(database))` and call it `connection`:
  - Checks that `connection.execute('SELECT COUNT(*) FROM customers').fetchone()` equals `(20,)`.
  - Sets `tables` to `{row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}`.
- Checks that `{'customers', 'ledger', 'processed_messages'}` is at most `tables`.

Names used here:

- `.fetchone()` reads the next result row, or `None`.
- `.execute(sql, values)` runs one SQL statement; `?` placeholders are filled from `values` safely.

**Lines 40 to 44**

```python
def test_without_the_migration_the_idempotency_table_does_not_exist(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=False)
    with closing(sqlite3.connect(database)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "processed_messages" not in tables
```

**Function `test_without_the_migration_the_idempotency_table_does_not_exist`** takes `database`, `sql_dir`.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=False)`.
- Inside a block that `closing(sqlite3.connect(database))` and call it `connection`:
  - Sets `tables` to `{row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}`.
- Checks that `'processed_messages'` is not inside `tables`.

**Lines 47 to 52**

```python
def test_the_ledger_has_no_unique_key_on_the_order_id_so_the_naive_mode_can_write_a_duplicate(ledger):
    first = ledger.apply("m-1", _command(1), 1, deduplicate=False)
    second = ledger.apply("m-1", _command(1), 2, deduplicate=False)
    assert first.applied
    assert second.applied
    assert [row.delivery_count for row in ledger.rows()] == [1, 2]
```

**Function `test_the_ledger_has_no_unique_key_on_the_order_id_so_the_naive_mode_can_write_a_duplicate`** takes `ledger`.

What happens, step by step:

- Sets `first` to the result of calling `ledger.apply('m-1', _command(1), 1, deduplicate=False)`.
- Sets `second` to the result of calling `ledger.apply('m-1', _command(1), 2, deduplicate=False)`.
- Checks that `first.applied` is true.
- Checks that `second.applied` is true.
- Checks that `[row.delivery_count for row in ledger.rows()]` equals `[1, 2]`.

**Lines 55 to 59**

```python
def test_the_idempotent_mode_writes_once_and_skips_the_repeat(ledger):
    assert ledger.apply("m-1", _command(1), 1, deduplicate=True).applied
    repeat = ledger.apply("m-1", _command(1), 2, deduplicate=True)
    assert repeat.applied is False
    assert len(ledger.rows()) == 1
```

**Function `test_the_idempotent_mode_writes_once_and_skips_the_repeat`** takes `ledger`.

What happens, step by step:

- Checks that `ledger.apply('m-1', _command(1), 1, deduplicate=True).applied` is true.
- Sets `repeat` to the result of calling `ledger.apply('m-1', _command(1), 2, deduplicate=True)`.
- Checks that `repeat.applied` is exactly `False`.
- Checks that `len(ledger.rows())` equals `1`.

**Lines 62 to 66**

```python
def test_the_previous_sequence_is_the_customers_highest_applied_before_the_write(ledger):
    assert ledger.apply("m-1", _command(1), 1, deduplicate=True).previous_seq == 0
    assert ledger.apply("m-2", _command(2), 1, deduplicate=True).previous_seq == 1
    assert ledger.apply("m-9", _command(9), 1, deduplicate=True).previous_seq == 2
    assert ledger.apply("m-x", _command(1, "c02"), 1, deduplicate=True).previous_seq == 0
```

**Function `test_the_previous_sequence_is_the_customers_highest_applied_before_the_write`** takes `ledger`.

What happens, step by step:

- Checks that `ledger.apply('m-1', _command(1), 1, deduplicate=True).previous_seq` equals `0`.
- Checks that `ledger.apply('m-2', _command(2), 1, deduplicate=True).previous_seq` equals `1`.
- Checks that `ledger.apply('m-9', _command(9), 1, deduplicate=True).previous_seq` equals `2`.
- Checks that `ledger.apply('m-x', _command(1, 'c02'), 1, deduplicate=True).previous_seq` equals `0`.

**Lines 69 to 74**

```python
def test_an_unknown_customer_is_a_permanent_error_and_the_message_id_is_not_recorded(ledger, database):
    with pytest.raises(UnknownCustomerError):
        ledger.apply("m-bad", _command(1, "c99"), 1, deduplicate=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM processed_messages").fetchone() == (0,)
    assert ledger.rows() == []  # rolled back, so a later fix of the customer table could still process it
```

**Function `test_an_unknown_customer_is_a_permanent_error_and_the_message_id_is_not_recorded`** takes `ledger`, `database`.

**New idea.** `with pytest.raises(SomeError):` is a context manager that expects the block to raise `SomeError`. The test passes only if that error is raised; if nothing is raised or a different error is raised, the test fails. `match="text"` also requires the error message to match the pattern.

What happens, step by step:

- Inside a block that expects an error: `pytest.raises(UnknownCustomerError)`:
  - Calls `ledger.apply('m-bad', _command(1, 'c99'), 1, deduplicate=True)`.
- Inside a block that `closing(sqlite3.connect(database))` and call it `connection`:
  - Checks that `connection.execute('SELECT COUNT(*) FROM processed_messages').fetchone()` equals `(0,)`.
- Checks that `ledger.rows()` equals `[]`.

**Lines 77 to 83**

```python
def test_amounts_are_stored_as_integer_cents(ledger, database):
    ledger.apply("m-1", OrderCommand("o-1", "c01", 1, 1999), 1, deduplicate=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT amount_cents, typeof(amount_cents) FROM ledger").fetchone() == (
            1999,
            "integer",
        )
```

**Function `test_amounts_are_stored_as_integer_cents`** takes `ledger`, `database`.

What happens, step by step:

- Calls `ledger.apply('m-1', OrderCommand('o-1', 'c01', 1, 1999), 1, deduplicate=True)`.
- Inside a block that `closing(sqlite3.connect(database))` and call it `connection`:
  - Checks that `connection.execute('SELECT amount_cents, typeof(amount_cents) FROM ledger').fetchone()` equals `(1999, 'integer')`.

**Lines 86 to 97**

```python
def test_a_locked_database_is_a_transient_error(ledger, database, monkeypatch):
    holder = sqlite3.connect(database, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        short_wait = sqlite3.connect(database, isolation_level=None, timeout=0.05)
        monkeypatch.setattr(ledger, "_connection", short_wait)
        with pytest.raises(TransientError):
            ledger.apply("m-1", _command(1), 1, deduplicate=True)
        short_wait.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()
```

**Function `test_a_locked_database_is_a_transient_error`** takes `ledger`, `database`, `monkeypatch`.

**New idea.** `monkeypatch` is a built-in pytest fixture that temporarily replaces an attribute, an environment variable or a dictionary entry for the duration of one test and restores the original afterwards.

What happens, step by step:

- Sets `holder` to the result of calling `sqlite3.connect(database, isolation_level=None)`.
- Calls `holder.execute('BEGIN IMMEDIATE')`.
- Try:
  - Sets `short_wait` to the result of calling `sqlite3.connect(database, isolation_level=None, timeout=0.05)`.
  - Calls `monkeypatch.setattr(ledger, '_connection', short_wait)`.
  - Inside a block that expects an error: `pytest.raises(TransientError)`:
    - Calls `ledger.apply('m-1', _command(1), 1, deduplicate=True)`.
  - Calls `short_wait.close()`.
- Always, in the end:
  - Calls `holder.execute('ROLLBACK')`.
  - Calls `holder.close()`.

Names used here:

- `setattr(obj, "name", value)` sets the attribute whose name is given as text.

**Lines 100 to 103**

```python
def test_the_readiness_check_follows_the_file(database, sql_dir, tmp_path):
    assert is_reachable(tmp_path / "missing" / "nope.db") is False
    prepare_database(database, sql_dir, with_migrations=True)
    assert is_reachable(database) is True
```

**Function `test_the_readiness_check_follows_the_file`** takes `database`, `sql_dir`, `tmp_path`.

What happens, step by step:

- Checks that `is_reachable(tmp_path / 'missing' / 'nope.db')` is exactly `False`.
- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Checks that `is_reachable(database)` is exactly `True`.

**Lines 106 to 120**

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

**New idea.** A **command-line program** reads its options from the words typed after its name (`tool run --count 3`). The standard `argparse` module declares the allowed options and prints a help text and a clear error for a wrong one.

What happens, step by step:

- Sets `_WORKER` to the result of calling `textwrap.dedent` with `'\n import sys\n from pathlib import Path\n from order_worker.domain.commands import OrderCommand\n …` (long; see the quote).

**Lines 123 to 134**

```python
def test_four_processes_writing_the_same_file_lose_no_row_and_duplicate_none(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    processes = [
        subprocess.Popen([sys.executable, "-c", _WORKER, str(database), str(start), "200"])
        for start in (0, 200, 400, 600)
    ]
    assert [process.wait(timeout=120) for process in processes] == [0, 0, 0, 0]
    ledger = SqliteLedger(database)
    try:
        assert len(ledger.rows()) == 800
    finally:
        ledger.close()
```

**Function `test_four_processes_writing_the_same_file_lose_no_row_and_duplicate_none`** takes `database`, `sql_dir`.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `processes` to `[subprocess.Popen([sys.executable, '-c', _WORKER, str(database), str(start), '200']) for start in (0, 200, 40…` (long; see the quote).
- Checks that `[process.wait(timeout=120) for process in processes]` equals `[0, 0, 0, 0]`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Try:
  - Checks that `len(ledger.rows())` equals `800`.
- Always, in the end:
  - Calls `ledger.close()`.

Names used here:

- `str(x)` turns a value into text.

**Lines 137 to 154**

```python
def test_the_sql_query_script_runs_against_a_real_database(database, sql_dir):
    sqlite3_cli = subprocess.run(["sqlite3", "-version"], capture_output=True, check=False)
    if sqlite3_cli.returncode != 0:
        pytest.skip("the sqlite3 shell is not installed")
    prepare_database(database, sql_dir, with_migrations=True)
    ledger = SqliteLedger(database)
    ledger.apply("m-1", _command(1), 1, deduplicate=True)
    ledger.close()
    result = subprocess.run(
        ["sqlite3", str(database)],
        input=Path(sql_dir / "003_queries.sql").read_text(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout
    assert "10.0" in result.stdout
```

**Function `test_the_sql_query_script_runs_against_a_real_database`** takes `database`, `sql_dir`.

**New idea.** `if condition:` runs its block only when the condition is true; `elif` adds another test; `else` is what runs when none matched.

What happens, step by step:

- Sets `sqlite3_cli` to the result of calling `subprocess.run(['sqlite3', '-version'], capture_output=True, check=False)`.
- If `sqlite3_cli.returncode` does not equal `0`:
  - Calls `pytest.skip('the sqlite3 shell is not installed')`.
- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Calls `ledger.apply('m-1', _command(1), 1, deduplicate=True)`.
- Calls `ledger.close()`.
- Sets `result` to the result of calling `subprocess.run` with `['sqlite3', str(database)]`; `input` set to `Path(sql_dir / '003_queries.sql').read_text()`; `capture_output` set to `True`; `text` set to `True`; `check` set to `False`.
- Checks that `result.returncode` equals `0`. If not, the failure message is `result.stderr`.
- Checks that `'1'` is one of / is inside `result.stdout`.
- Checks that `'10.0'` is one of / is inside `result.stdout`.

Names used here:

- `pytest.skip(reason)` skips the test.
- `Path.read_text()` reads a whole file as text.

#### `tests/unit/application/fakes.py`

101 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Hand-written test doubles for the application ports."""
```

The module docstring says: Hand-written test doubles for the application ports.

**Line 3**

```python
from collections.abc import Sequence
```

What happens, step by step:

- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 5 to 8**

```python
from order_worker.application.ports import OutgoingMessage
from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import LockLostError, TransientError, UnknownCustomerError
from order_worker.domain.processing import ApplyResult
```

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `OrderCommand` from the repository's own module `order_worker.domain.commands`: One order: who ordered, which order, the customer's sequence number and the amount in cents (defined in `src/order_worker/domain/commands.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)
- `TransientError` from the repository's own module `order_worker.domain.errors`: A failure that a retry may fix (a busy database): the message is abandoned and delivered again (defined in `src/order_worker/domain/errors.py`)
- `UnknownCustomerError` from the repository's own module `order_worker.domain.errors`: The command names a customer that does not exist (defined in `src/order_worker/domain/errors.py`)
- `ApplyResult` from the repository's own module `order_worker.domain.processing`: What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write (defined in `src/order_worker/domain/processing.py`)

**Lines 11 to 12**

```python
class FakeDelivery:
    """A delivery that records how it was settled, in order, with the other fakes' events."""
```

The docstring in the code says: A delivery that records how it was settled, in order, with the other fakes' events.

**Class `FakeDelivery`**.

**Lines 14 to 33**

```python
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
```

**Method `__init__`** takes `body` (type `bytes`), `message_id` (type `str`), default `'m-1'`, `delivery_count` (type `int`), default `1`, `session_id` (type `str | None`), default `None`, `events` (type `list[str] | None`), default `None`, `lock_lost` (type `bool`), default `False`, `reason` (type `str | None`), default `None`, `description` (type `str | None`), default `None`; gives back `None`.

**New idea.** `__init__` is the special method Python calls right after it creates an object; it sets the object's starting attributes. Names with double underscores on both sides are **dunder methods**: Python calls them for you in response to syntax (`__init__` on creation, `__repr__` when printing, `__len__` for `len(x)`, `__eq__` for `==`).

**New idea.** `a if condition else b` is an expression that gives `a` when the condition is true and `b` otherwise.

**New idea.** Square brackets after a type, as in `list[str]` or `dict[str, int]`, say what the container holds: a list of text, or a dictionary from text to whole numbers.

**New idea.** `A | B` in a type hint means "either an A or a B". `str | None` means "text, or nothing at all".

What happens, step by step:

- Sets `self.body` to `body`.
- Sets `self.message_id` to `message_id`.
- Sets `self.delivery_count` to `delivery_count`.
- Sets `self.session_id` to `session_id`.
- Sets `self.dead_letter_reason` to `reason`.
- Sets `self.dead_letter_description` to `description`.
- Sets `self.events` to `events if events is not None else []`.
- Sets `self.lock_lost` to `lock_lost`.
- Sets `self.settled` with type `list[str]` and starting value `[]`.

**Lines 35 to 39**

```python
    def _settle(self, verb: str) -> None:
        if self.lock_lost:
            raise LockLostError("lock lost")
        self.settled.append(verb)
        self.events.append(f"settle:{verb}")
```

**Method `_settle`** takes `verb` (type `str`); gives back `None`.

What happens, step by step:

- If `self.lock_lost` is true:
  - Raises `LockLostError('lock lost')`.
- Calls `self.settled.append(verb)`.
- Calls `self.events.append(f'settle:{verb}')`.

Names used here:

- `.append(x)` adds `x` to the end of a list.

**Lines 41 to 42**

```python
    def complete(self) -> None:
        self._settle("complete")
```

**Method `complete`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._settle('complete')`.

**Lines 44 to 45**

```python
    def abandon(self) -> None:
        self._settle("abandon")
```

**Method `abandon`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._settle('abandon')`.

**Lines 47 to 48**

```python
    def dead_letter(self, reason: str, description: str) -> None:
        self._settle(f"dead-letter:{reason}:{description}")
```

**Method `dead_letter`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

What happens, step by step:

- Calls `self._settle(f'dead-letter:{reason}:{description}')`.

**Lines 51 to 52**

```python
class FakeLedger:
    """Records applies; can be told to raise, or to report a duplicate or a previous sequence."""
```

The docstring in the code says: Records applies; can be told to raise, or to report a duplicate or a previous sequence.

**Class `FakeLedger`**.

**Lines 54 to 59**

```python
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.calls: list[tuple[str, OrderCommand, int, bool]] = []
        self.seen: set[str] = set()
        self.raise_error: Exception | None = None
        self.previous_seq = 0
```

**Method `__init__`** takes `events` (type `list[str] | None`), default `None`; gives back `None`.

What happens, step by step:

- Sets `self.events` to `events if events is not None else []`.
- Sets `self.calls` with type `list[tuple[str, OrderCommand, int, bool]]` and starting value `[]`.
- Sets `self.seen` with type `set[str]` and starting value `set()`.
- Sets `self.raise_error` with type `Exception | None` and starting value `None`.
- Sets `self.previous_seq` to `0`.

Names used here:

- `set(x)` builds a set: a collection with no duplicates.

**Lines 61 to 69**

```python
    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        if self.raise_error is not None:
            raise self.raise_error
        self.calls.append((message_id, command, delivery_count, deduplicate))
        self.events.append(f"apply:{command.order_id}")
        if deduplicate and message_id in self.seen:
            return ApplyResult(applied=False, previous_seq=0)
        self.seen.add(message_id)
        return ApplyResult(applied=True, previous_seq=self.previous_seq)
```

**Method `apply`** takes `message_id` (type `str`), `command` (type `OrderCommand`), `delivery_count` (type `int`), `deduplicate` (by name only), type `bool`; gives back `ApplyResult`.

**New idea.** A bare `*` in a parameter list means every parameter after it must be passed by name (`f(x=1)`) and cannot be passed by position. This prevents mixing up arguments.

**New idea.** `and` is true when both sides are; `or` is true when either is, and it stops at the first true side. `not` flips true and false.

What happens, step by step:

- If `self.raise_error` is not exactly `None`:
  - Raises `self.raise_error`.
- Calls `self.calls.append((message_id, command, delivery_count, deduplicate))`.
- Calls `self.events.append(f'apply:{command.order_id}')`.
- If `deduplicate` is true **and** `message_id` is one of / is inside `self.seen`:
  - Returns `ApplyResult(applied=False, previous_seq=0)`.
- Calls `self.seen.add(message_id)`.
- Returns `ApplyResult(applied=True, previous_seq=self.previous_seq)`.

Names used here:

- `add` is the repository's own: Count one handled delivery (defined in `src/order_worker/application/run_worker.py`)

**Line 72**

```python
class FakeClock:
```

**Class `FakeClock`**.

**Lines 73 to 75**

```python
    def __init__(self) -> None:
        self.time = 0.0
        self.slept: list[float] = []
```

**Method `__init__`** takes no parameters; gives back `None`.

What happens, step by step:

- Sets `self.time` to `0.0`.
- Sets `self.slept` with type `list[float]` and starting value `[]`.

**Lines 77 to 78**

```python
    def now(self) -> float:
        return self.time
```

**Method `now`** takes no parameters; gives back `float`.

What happens, step by step:

- Returns `self.time`.

**Lines 80 to 82**

```python
    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.time += seconds
```

**Method `sleep`** takes `seconds` (type `float`); gives back `None`.

**New idea.** `x += 1` is shorthand for `x = x + 1`; `-=`, `*=` and `|=` work the same way.

What happens, step by step:

- Calls `self.slept.append(seconds)`.
- Updates `self.time` with `=` `seconds`.

**Lines 85 to 86**

```python
class ScriptedReceiver:
    """Yields the scripted deliveries, then None; counts closes."""
```

The docstring in the code says: Yields the scripted deliveries, then None; counts closes.

**Class `ScriptedReceiver`**.

**Lines 88 to 94**

```python
    def __init__(
        self, deliveries: Sequence[FakeDelivery], clock: FakeClock | None = None, on_empty: float = 0.0
    ) -> None:
        self._deliveries = list(deliveries)
        self.closed = 0
        self._clock = clock
        self._on_empty = on_empty
```

**Method `__init__`** takes `deliveries` (type `Sequence[FakeDelivery]`), `clock` (type `FakeClock | None`), default `None`, `on_empty` (type `float`), default `0.0`; gives back `None`.

What happens, step by step:

- Sets `self._deliveries` to the result of calling `list(deliveries)`.
- Sets `self.closed` to `0`.
- Sets `self._clock` to `clock`.
- Sets `self._on_empty` to `on_empty`.

Names used here:

- `list(x)` builds a list from any sequence.

**Lines 96 to 101**

```python
    def receive(self, max_wait_seconds: float) -> FakeDelivery | None:
        if self._deliveries:
            return self._deliveries.pop(0)
        if self._clock is not None:
            self._clock.sleep(self._on_empty or max_wait_seconds)
        return None
```

**Method `receive`** takes `max_wait_seconds` (type `float`); gives back `FakeDelivery | None`.

What happens, step by step:

- If `self._deliveries` is true:
  - Returns `self._deliveries.pop(0)`.
- If `self._clock` is not exactly `None`:
  - Calls `self._clock.sleep(self._on_empty or max_wait_seconds)`.
- Returns `None`.

Names used here:

- `.pop()` removes and returns an item.

**Lines 103 to 104**

```python
    def close(self) -> None:
        self.closed += 1
```

**Method `close`** takes no parameters; gives back `None`.

What happens, step by step:

- Updates `self.closed` with `=` `1`.

**Lines 107 to 108**

```python
class FakeInbox:
    """Opens the scripted receivers in turn; None when they run out."""
```

The docstring in the code says: Opens the scripted receivers in turn; None when they run out.

**Class `FakeInbox`**.

**Lines 110 to 112**

```python
    def __init__(self, *receivers: ScriptedReceiver | None) -> None:
        self._receivers = list(receivers)
        self.opened = 0
```

**Method `__init__`** takes `*receivers` (all extra positional values); gives back `None`.

What happens, step by step:

- Sets `self._receivers` to the result of calling `list(receivers)`.
- Sets `self.opened` to `0`.

**Lines 114 to 116**

```python
    def open(self) -> ScriptedReceiver | None:
        self.opened += 1
        return self._receivers.pop(0) if self._receivers else None
```

**Method `open`** takes no parameters; gives back `ScriptedReceiver | None`.

What happens, step by step:

- Updates `self.opened` with `=` `1`.
- Returns `self._receivers.pop(0) if self._receivers else None`.

**Line 119**

```python
class RecordingSender:
```

**Class `RecordingSender`**.

**Lines 120 to 122**

```python
    def __init__(self, events: list[str] | None = None) -> None:
        self.sent: list[OutgoingMessage] = []
        self.events = events if events is not None else []
```

**Method `__init__`** takes `events` (type `list[str] | None`), default `None`; gives back `None`.

What happens, step by step:

- Sets `self.sent` with type `list[OutgoingMessage]` and starting value `[]`.
- Sets `self.events` to `events if events is not None else []`.

**Lines 124 to 126**

```python
    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        self.sent.extend(messages)
        self.events.extend(f"send:{message.message_id}" for message in messages)
```

**Method `send`** takes `messages` (type `Sequence[OutgoingMessage]`); gives back `None`.

What happens, step by step:

- Calls `self.sent.extend(messages)`.
- Calls `self.events.extend((f'send:{message.message_id}' for message in messages))`.

Names used here:

- `.extend(items)` adds every item to the end of a list.

**Lines 129 to 130**

```python
def transient() -> TransientError:
    return TransientError("busy")
```

**Function `transient`** takes no parameters; gives back `TransientError`.

What happens, step by step:

- Returns `TransientError('busy')`.

**Lines 133 to 134**

```python
def unknown_customer() -> UnknownCustomerError:
    return UnknownCustomerError("c99")
```

**Function `unknown_customer`** takes no parameters; gives back `UnknownCustomerError`.

What happens, step by step:

- Returns `UnknownCustomerError('c99')`.

#### `tests/unit/application/test_handle_delivery.py`

95 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 2**

```python
import json
import logging
```

What happens, step by step:

- `json`: the standard-library module for JSON.
- `logging`: the standard-library module for log records.

**Line 4**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 6 to 8**

```python
from order_worker.application.handle_delivery import Effect, HandleDelivery
from order_worker.domain.processing import Chaos, Mode
from tests.unit.application.fakes import FakeClock, FakeDelivery, FakeLedger, transient, unknown_customer
```

What happens, step by step:

- `Effect` from the repository's own module `order_worker.application.handle_delivery`: What happened to the message (defined in `src/order_worker/application/handle_delivery.py`)
- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `Chaos` from the repository's own module `order_worker.domain.processing`: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit (defined in `src/order_worker/domain/processing.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `FakeClock` from the test helper module `tests.unit.application.fakes`: no description in the code (defined in `tests/unit/application/fakes.py`).
- `FakeDelivery` from the test helper module `tests.unit.application.fakes`: A delivery that records how it was settled, in order, with the other fakes' events (defined in `tests/unit/application/fakes.py`).
- `FakeLedger` from the test helper module `tests.unit.application.fakes`: Records applies; can be told to raise, or to report a duplicate or a previous sequence (defined in `tests/unit/application/fakes.py`).
- `transient` from the test helper module `tests.unit.application.fakes`: no description in the code (defined in `tests/unit/application/fakes.py`).
- `unknown_customer` from the test helper module `tests.unit.application.fakes`: no description in the code (defined in `tests/unit/application/fakes.py`).

**Lines 11 to 14**

```python
def _command(seq: int = 1, amount: object = 10.0, customer: str = "c01") -> bytes:
    return json.dumps(
        {"orderId": f"o-{customer}-{seq:03d}", "customerId": customer, "seq": seq, "amount": amount}
    ).encode()
```

**New idea.** **UTF-8** is the standard way to store text as bytes, able to represent every language. A program that reads a file must decode the bytes with the right encoding to get text back.

**Function `_command`** takes `seq` (type `int`), default `1`, `amount` (type `object`), default `10.0`, `customer` (type `str`), default `'c01'`; gives back `bytes`.

What happens, step by step:

- Returns `json.dumps({'orderId': f'o-{customer}-{seq:03d}', 'customerId': customer, 'seq': seq, 'amount': amount}).enco…` (long; see the quote).

Names used here:

- `.encode("utf-8")` turns text into bytes.

**Lines 17 to 23**

```python
def test_the_message_is_completed_only_after_the_ledger_write():
    events: list[str] = []
    ledger = FakeLedger(events)
    delivery = FakeDelivery(_command(), events=events)
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert events == ["apply:o-c01-001", "settle:complete"]
    assert (handled.effect, handled.settled) == (Effect.APPLIED, True)
```

**Function `test_the_message_is_completed_only_after_the_ledger_write`** takes no parameters.

What happens, step by step:

- Sets `events` with type `list[str]` and starting value `[]`.
- Sets `ledger` to the result of calling `FakeLedger(events)`.
- Sets `delivery` to the result of calling `FakeDelivery(_command(), events=events)`.
- Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `events` equals `['apply:o-c01-001', 'settle:complete']`.
- Checks that `(handled.effect, handled.settled)` equals `(Effect.APPLIED, True)`.

Names used here:

- `handle` is the repository's own: Process `delivery`; never raises for a failure the queue can handle (defined in `src/order_worker/application/handle_delivery.py`)

**Lines 26 to 32**

```python
def test_a_crash_inside_the_write_leaves_the_message_unsettled_so_the_queue_redelivers_it():
    ledger = FakeLedger()
    ledger.raise_error = RuntimeError("process killed")
    delivery = FakeDelivery(_command())
    with pytest.raises(RuntimeError):
        HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert delivery.settled == []
```

**Function `test_a_crash_inside_the_write_leaves_the_message_unsettled_so_the_queue_redelivers_it`** takes no parameters.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.raise_error` to the result of calling `RuntimeError('process killed')`.
- Sets `delivery` to the result of calling `FakeDelivery(_command())`.
- Inside a block that expects an error: `pytest.raises(RuntimeError)`:
  - Calls `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `delivery.settled` equals `[]`.

Names used here:

- `RuntimeError` is the general error for a failure that fits no other class.

**Lines 35 to 39**

```python
def test_the_idempotent_mode_asks_the_ledger_to_deduplicate_and_the_naive_mode_does_not():
    for mode, expected in ((Mode.IDEMPOTENT, True), (Mode.NAIVE, False)):
        ledger = FakeLedger()
        HandleDelivery(ledger, FakeClock(), mode).handle(FakeDelivery(_command()))
        assert ledger.calls[0][3] is expected
```

**Function `test_the_idempotent_mode_asks_the_ledger_to_deduplicate_and_the_naive_mode_does_not`** takes no parameters.

**New idea.** `for item in things:` runs its block once for each element of `things`, with `item` set to that element.

What happens, step by step:

- For each `(mode, expected)` in `((Mode.IDEMPOTENT, True), (Mode.NAIVE, False))`:
  - Sets `ledger` to the result of calling `FakeLedger()`.
  - Calls `HandleDelivery(ledger, FakeClock(), mode).handle(FakeDelivery(_command()))`.
  - Checks that `ledger.calls[0][3]` is exactly `expected`.

**Lines 42 to 49**

```python
def test_a_repeated_message_is_skipped_but_still_completed():
    ledger = FakeLedger()
    handler = HandleDelivery(ledger, FakeClock())
    handler.handle(FakeDelivery(_command(), message_id="same"))
    second = FakeDelivery(_command(), message_id="same", delivery_count=2)
    handled = handler.handle(second)
    assert handled.effect is Effect.SKIPPED_DUPLICATE
    assert second.settled == ["complete"]
```

**Function `test_a_repeated_message_is_skipped_but_still_completed`** takes no parameters.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `handler` to the result of calling `HandleDelivery(ledger, FakeClock())`.
- Calls `handler.handle(FakeDelivery(_command(), message_id='same'))`.
- Sets `second` to the result of calling `FakeDelivery(_command(), message_id='same', delivery_count=2)`.
- Sets `handled` to the result of calling `handler.handle(second)`.
- Checks that `handled.effect` is exactly `Effect.SKIPPED_DUPLICATE`.
- Checks that `second.settled` equals `['complete']`.

**Lines 52 to 58**

```python
def test_a_poison_message_is_dead_lettered_at_once_with_its_reason_and_description():
    ledger = FakeLedger()
    delivery = FakeDelivery(_command(amount="abc"))
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert handled.effect is Effect.DEAD_LETTERED
    assert delivery.settled == ["dead-letter:InvalidAmount:amount is not a number"]
    assert ledger.calls == []  # nothing was written
```

**Function `test_a_poison_message_is_dead_lettered_at_once_with_its_reason_and_description`** takes no parameters.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `delivery` to the result of calling `FakeDelivery(_command(amount='abc'))`.
- Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `handled.effect` is exactly `Effect.DEAD_LETTERED`.
- Checks that `delivery.settled` equals `['dead-letter:InvalidAmount:amount is not a number']`.
- Checks that `ledger.calls` equals `[]`.

**Lines 61 to 67**

```python
def test_a_command_the_ledger_can_never_accept_is_dead_lettered_too():
    ledger = FakeLedger()
    ledger.raise_error = unknown_customer()
    delivery = FakeDelivery(_command(customer="c99"))
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert handled.effect is Effect.DEAD_LETTERED
    assert delivery.settled[0].startswith("dead-letter:UnknownCustomer")
```

**Function `test_a_command_the_ledger_can_never_accept_is_dead_lettered_too`** takes no parameters.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.raise_error` to the result of calling `unknown_customer()`.
- Sets `delivery` to the result of calling `FakeDelivery(_command(customer='c99'))`.
- Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `handled.effect` is exactly `Effect.DEAD_LETTERED`.
- Checks that `delivery.settled[0].startswith('dead-letter:UnknownCustomer')` is true.

Names used here:

- `.startswith(prefix)` is true when the text begins with `prefix`.

**Lines 70 to 75**

```python
def test_a_transient_failure_abandons_the_message_so_it_is_tried_again():
    ledger = FakeLedger()
    ledger.raise_error = transient()
    delivery = FakeDelivery(_command())
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert (handled.effect, delivery.settled) == (Effect.ABANDONED, ["abandon"])
```

**Function `test_a_transient_failure_abandons_the_message_so_it_is_tried_again`** takes no parameters.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.raise_error` to the result of calling `transient()`.
- Sets `delivery` to the result of calling `FakeDelivery(_command())`.
- Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `(handled.effect, delivery.settled)` equals `(Effect.ABANDONED, ['abandon'])`.

**Lines 78 to 84**

```python
def test_a_lost_lock_on_complete_is_logged_not_raised_and_the_effect_stands(caplog):
    ledger = FakeLedger()
    delivery = FakeDelivery(_command(), lock_lost=True)
    with caplog.at_level(logging.WARNING, logger="order_worker.handler"):
        handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert (handled.effect, handled.settled) == (Effect.APPLIED, False)
    assert "complete failed for o-c01-001: the lock supplied is invalid" in caplog.text
```

**Function `test_a_lost_lock_on_complete_is_logged_not_raised_and_the_effect_stands`** takes `caplog`.

**New idea.** `caplog` is a built-in pytest fixture that collects the log records written during the test so the test can check them (`caplog.records`, `caplog.text`).

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `delivery` to the result of calling `FakeDelivery(_command(), lock_lost=True)`.
- Inside a block that `caplog.at_level(logging.WARNING, logger='order_worker.handler')`:
  - Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(delivery)`.
- Checks that `(handled.effect, handled.settled)` equals `(Effect.APPLIED, False)`.
- Checks that `'complete failed for o-c01-001: the lock supplied is invalid'` is one of / is inside `caplog.text`.

**Lines 87 to 93**

```python
def test_a_lost_lock_on_dead_letter_and_on_abandon_is_also_tolerated():
    poison = FakeDelivery(_command(amount="abc"), lock_lost=True)
    assert HandleDelivery(FakeLedger(), FakeClock()).handle(poison).settled is False
    ledger = FakeLedger()
    ledger.raise_error = transient()
    busy = FakeDelivery(_command(), lock_lost=True)
    assert HandleDelivery(ledger, FakeClock()).handle(busy).settled is False
```

**Function `test_a_lost_lock_on_dead_letter_and_on_abandon_is_also_tolerated`** takes no parameters.

What happens, step by step:

- Sets `poison` to the result of calling `FakeDelivery(_command(amount='abc'), lock_lost=True)`.
- Checks that `HandleDelivery(FakeLedger(), FakeClock()).handle(poison).settled` is exactly `False`.
- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.raise_error` to the result of calling `transient()`.
- Sets `busy` to the result of calling `FakeDelivery(_command(), lock_lost=True)`.
- Checks that `HandleDelivery(ledger, FakeClock()).handle(busy).settled` is exactly `False`.

**Lines 96 to 102**

```python
def test_chaos_sleeps_before_the_write_on_the_first_delivery_only():
    clock = FakeClock()
    handler = HandleDelivery(FakeLedger(), clock, chaos=Chaos(slow_every=10, slow_seconds=45))
    handler.handle(FakeDelivery(_command(seq=10), delivery_count=1))
    handler.handle(FakeDelivery(_command(seq=10), delivery_count=2, message_id="m-2"))
    handler.handle(FakeDelivery(_command(seq=11), message_id="m-3"))
    assert clock.slept == [45.0]
```

**Function `test_chaos_sleeps_before_the_write_on_the_first_delivery_only`** takes no parameters.

What happens, step by step:

- Sets `clock` to the result of calling `FakeClock()`.
- Sets `handler` to the result of calling `HandleDelivery(FakeLedger(), clock, chaos=Chaos(slow_every=10, slow_seconds=45))`.
- Calls `handler.handle(FakeDelivery(_command(seq=10), delivery_count=1))`.
- Calls `handler.handle(FakeDelivery(_command(seq=10), delivery_count=2, message_id='m-2'))`.
- Calls `handler.handle(FakeDelivery(_command(seq=11), message_id='m-3'))`.
- Checks that `clock.slept` equals `[45.0]`.

**Lines 105 to 108**

```python
def test_the_log_shows_the_lessons_apply_line_with_the_sleep_note(caplog):
    with caplog.at_level(logging.INFO, logger="order_worker.handler"):
        HandleDelivery(FakeLedger(), FakeClock(), chaos=Chaos(slow_every=10)).handle(FakeDelivery(_command(seq=10)))
    assert "apply o-c01-010 delivery_count=1 (sleeping 45 s)" in caplog.text
```

**Function `test_the_log_shows_the_lessons_apply_line_with_the_sleep_note`** takes `caplog`.

What happens, step by step:

- Inside a block that `caplog.at_level(logging.INFO, logger='order_worker.handler')`:
  - Calls `HandleDelivery(FakeLedger(), FakeClock(), chaos=Chaos(slow_every=10)).handle` with `FakeDelivery(_command(seq=10))`.
- Checks that `'apply o-c01-010 delivery_count=1 (sleeping 45 s)'` is one of / is inside `caplog.text`.

**Lines 111 to 117**

```python
def test_a_command_applied_out_of_order_is_logged_as_an_error_and_still_applied(caplog):
    ledger = FakeLedger()
    ledger.previous_seq = 14  # the customer already has seq 14, and this is seq 10
    with caplog.at_level(logging.ERROR, logger="order_worker.handler"):
        handled = HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))
    assert handled.effect is Effect.APPLIED
    assert "out of order: customer c01 applied seq 10 after seq 14" in caplog.text
```

**Function `test_a_command_applied_out_of_order_is_logged_as_an_error_and_still_applied`** takes `caplog`.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.previous_seq` to `14`.
- Inside a block that `caplog.at_level(logging.ERROR, logger='order_worker.handler')`:
  - Sets `handled` to the result of calling `HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))`.
- Checks that `handled.effect` is exactly `Effect.APPLIED`.
- Checks that `'out of order: customer c01 applied seq 10 after seq 14'` is one of / is inside `caplog.text`.

**Lines 120 to 125**

```python
def test_a_command_that_follows_its_predecessor_logs_no_out_of_order(caplog):
    ledger = FakeLedger()
    ledger.previous_seq = 9
    with caplog.at_level(logging.ERROR, logger="order_worker.handler"):
        HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))
    assert "out of order" not in caplog.text
```

**Function `test_a_command_that_follows_its_predecessor_logs_no_out_of_order`** takes `caplog`.

What happens, step by step:

- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `ledger.previous_seq` to `9`.
- Inside a block that `caplog.at_level(logging.ERROR, logger='order_worker.handler')`:
  - Calls `HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))`.
- Checks that `'out of order'` is not inside `caplog.text`.

#### `tests/unit/application/test_produce_replay_and_check.py`

106 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
import json
```

What happens, step by step:

- `json`: the standard-library module for JSON.

**Lines 3 to 7**

```python
from order_worker.application.check_ledger import CheckLedger
from order_worker.application.ports import OrderRow
from order_worker.application.produce_orders import ProduceOrders
from order_worker.application.replay_dead_letters import Action, ReplayDeadLetters
from tests.unit.application.fakes import FakeDelivery, FakeInbox, RecordingSender, ScriptedReceiver
```

What happens, step by step:

- `CheckLedger` from the repository's own module `order_worker.application.check_ledger`: Compare the ledger with the expected end state of the producer's known set (defined in `src/order_worker/application/check_ledger.py`)
- `OrderRow` from the repository's own module `order_worker.application.ports`: One ledger row, in the order it was applied (defined in `src/order_worker/application/ports.py`)
- `ProduceOrders` from the repository's own module `order_worker.application.produce_orders`: Send `customers x per_customer` commands, then one poison command that can never succeed (defined in `src/order_worker/application/produce_orders.py`)
- `Action` from the repository's own module `order_worker.application.replay_dead_letters`: What to do with one dead letter (defined in `src/order_worker/application/replay_dead_letters.py`)
- `ReplayDeadLetters` from the repository's own module `order_worker.application.replay_dead_letters`: Resubmit fixed messages to the main queue, then remove them from the dead-letter queue (defined in `src/order_worker/application/replay_dead_letters.py`)
- `FakeDelivery` from the test helper module `tests.unit.application.fakes`: A delivery that records how it was settled, in order, with the other fakes' events (defined in `tests/unit/application/fakes.py`).
- `FakeInbox` from the test helper module `tests.unit.application.fakes`: Opens the scripted receivers in turn; None when they run out (defined in `tests/unit/application/fakes.py`).
- `RecordingSender` from the test helper module `tests.unit.application.fakes`: no description in the code (defined in `tests/unit/application/fakes.py`).
- `ScriptedReceiver` from the test helper module `tests.unit.application.fakes`: Yields the scripted deliveries, then None; counts closes (defined in `tests/unit/application/fakes.py`).

**Lines 10 to 16**

```python
def test_the_producer_sends_a_thousand_commands_and_one_poison_command():
    sender = RecordingSender()
    sent = ProduceOrders(sender).run()
    assert sent == 1001
    assert sender.sent[-1].message_id == "o-bad"
    assert len({message.message_id for message in sender.sent}) == 1001
    assert all(message.session_id is None for message in sender.sent)
```

**Function `test_the_producer_sends_a_thousand_commands_and_one_poison_command`** takes no parameters.

What happens, step by step:

- Sets `sender` to the result of calling `RecordingSender()`.
- Sets `sent` to the result of calling `ProduceOrders(sender).run()`.
- Checks that `sent` equals `1001`.
- Checks that `sender.sent[-1].message_id` equals `'o-bad'`.
- Checks that `len({message.message_id for message in sender.sent})` equals `1001`.
- Checks that `all((message.session_id is None for message in sender.sent))` is true.

Names used here:

- `all(x)` is true if every item is true.

**Lines 19 to 23**

```python
def test_with_sessions_every_message_carries_its_customer_as_the_session_id():
    sender = RecordingSender()
    ProduceOrders(sender, use_sessions=True).run()
    assert all(message.session_id == json.loads(message.body)["customerId"] for message in sender.sent)
    assert sender.sent[-1].session_id == "c07"
```

**Function `test_with_sessions_every_message_carries_its_customer_as_the_session_id`** takes no parameters.

What happens, step by step:

- Sets `sender` to the result of calling `RecordingSender()`.
- Calls `ProduceOrders(sender, use_sessions=True).run()`.
- Checks that `all((message.session_id == json.loads(message.body)['customerId'] for message in sender.sent))` is true.
- Checks that `sender.sent[-1].session_id` equals `'c07'`.

Names used here:

- `json.loads(text)` turns JSON text into Python data.

**Lines 26 to 27**

```python
def test_the_producer_can_leave_out_the_poison_command():
    assert ProduceOrders(RecordingSender()).run(customers=2, per_customer=3, include_poison=False) == 6
```

**Function `test_the_producer_can_leave_out_the_poison_command`** takes no parameters.

What happens, step by step:

- Checks that `ProduceOrders(RecordingSender()).run(customers=2, per_customer=3, include_poison=False)` equals `6`.

**Lines 30 to 32**

```python
def _dead_letter(message_id="o-bad", reason="InvalidAmount", events=None, session_id=None):
    body = json.dumps({"orderId": message_id, "customerId": "c07", "seq": 51, "amount": "abc"}).encode()
    return FakeDelivery(body, message_id, 1, session_id, events, reason=reason, description="amount is not a number")
```

**Function `_dead_letter`** takes `message_id`, default `'o-bad'`, `reason`, default `'InvalidAmount'`, `events`, default `None`, `session_id`, default `None`.

What happens, step by step:

- Sets `body` to the result of calling `json.dumps({'orderId': message_id, 'customerId': 'c07', 'seq': 51, 'amount': 'abc'}).encode()`.
- Returns `FakeDelivery(body, message_id, 1, session_id, events, reason=reason, description='amount is not a number')`.

**Lines 35 to 44**

```python
def test_a_fixed_message_is_sent_with_its_original_id_before_the_dead_letter_is_removed():
    events: list[str] = []
    sender = RecordingSender(events)
    dead = _dead_letter(events=events, session_id="c07")
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()
    assert events == ["send:o-bad", "settle:complete"]  # send first, so a crash cannot lose the message
    assert (report.fixed, report.dropped, report.kept) == (1, 0, 0)
    assert sender.sent[0].message_id == "o-bad"
    assert sender.sent[0].session_id == "c07"
    assert json.loads(sender.sent[0].body)["amount"] == 10.0
```

**Function `test_a_fixed_message_is_sent_with_its_original_id_before_the_dead_letter_is_removed`** takes no parameters.

**New idea.** `lambda x: x + 1` is a small nameless function written in one expression: it takes `x` and returns `x + 1`.

What happens, step by step:

- Sets `events` with type `list[str]` and starting value `[]`.
- Sets `sender` to the result of calling `RecordingSender(events)`.
- Sets `dead` to the result of calling `_dead_letter(events=events, session_id='c07')`.
- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()`.
- Checks that `events` equals `['send:o-bad', 'settle:complete']`.
- Checks that `(report.fixed, report.dropped, report.kept)` equals `(1, 0, 0)`.
- Checks that `sender.sent[0].message_id` equals `'o-bad'`.
- Checks that `sender.sent[0].session_id` equals `'c07'`.
- Checks that `json.loads(sender.sent[0].body)['amount']` equals `10.0`.

**Lines 47 to 51**

```python
def test_a_dropped_message_is_removed_without_being_resubmitted():
    sender = RecordingSender()
    dead = _dead_letter()
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.DROP).run()
    assert (report.dropped, sender.sent, dead.settled) == (1, [], ["complete"])
```

**Function `test_a_dropped_message_is_removed_without_being_resubmitted`** takes no parameters.

What happens, step by step:

- Sets `sender` to the result of calling `RecordingSender()`.
- Sets `dead` to the result of calling `_dead_letter()`.
- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.DROP).run()`.
- Checks that `(report.dropped, sender.sent, dead.settled)` equals `(1, [], ['complete'])`.

**Lines 54 to 57**

```python
def test_a_kept_message_is_abandoned_and_stays_in_the_dead_letter_queue():
    dead = _dead_letter()
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), lambda _view: Action.KEEP).run()
    assert (report.kept, dead.settled) == (1, ["abandon"])
```

**Function `test_a_kept_message_is_abandoned_and_stays_in_the_dead_letter_queue`** takes no parameters.

What happens, step by step:

- Sets `dead` to the result of calling `_dead_letter()`.
- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), lambda _view: Action.KEEP).run()`.
- Checks that `(report.kept, dead.settled)` equals `(1, ['abandon'])`.

**Lines 60 to 64**

```python
def test_a_message_with_no_known_repair_is_kept_even_when_the_operator_says_fix():
    sender = RecordingSender()
    dead = _dead_letter(reason="UnknownCustomer")
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()
    assert (report.kept, report.fixed, sender.sent) == (1, 0, [])
```

**Function `test_a_message_with_no_known_repair_is_kept_even_when_the_operator_says_fix`** takes no parameters.

What happens, step by step:

- Sets `sender` to the result of calling `RecordingSender()`.
- Sets `dead` to the result of calling `_dead_letter(reason='UnknownCustomer')`.
- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()`.
- Checks that `(report.kept, report.fixed, sender.sent)` equals `(1, 0, [])`.

**Lines 67 to 81**

```python
def test_the_operator_sees_the_reason_the_description_and_the_delivery_count():
    seen = []
    dead = _dead_letter()

    def decide(view):
        seen.append(view)
        return Action.DROP

    ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), decide).run()
    assert (seen[0].message_id, seen[0].reason, seen[0].description, seen[0].delivery_count) == (
        "o-bad",
        "InvalidAmount",
        "amount is not a number",
        1,
    )
```

**Function `test_the_operator_sees_the_reason_the_description_and_the_delivery_count`** takes no parameters.

What happens, step by step:

- Sets `seen` to `[]`.
- Sets `dead` to the result of calling `_dead_letter()`.
- Defines the inner function `decide(view)`:
  - Calls `seen.append(view)`.
  - Returns `Action.DROP`.
- Calls `ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), decide).run()`.
- Checks that `(seen[0].message_id, seen[0].reason, seen[0].description, seen[0].delivery_count)` equals `('o-bad', 'InvalidAmount', 'amount is not a number', 1)`.

**Lines 84 to 88**

```python
def test_a_kept_message_that_comes_straight_back_ends_the_run_instead_of_looping():
    first, again = _dead_letter(), _dead_letter()
    receiver = ScriptedReceiver([first, again])
    report = ReplayDeadLetters(FakeInbox(receiver), RecordingSender(), lambda _view: Action.KEEP).run()
    assert (report.kept, again.settled, receiver.closed) == (1, ["abandon"], 1)
```

**Function `test_a_kept_message_that_comes_straight_back_ends_the_run_instead_of_looping`** takes no parameters.

What happens, step by step:

- Sets `(first, again)` to `(_dead_letter(), _dead_letter())`.
- Sets `receiver` to the result of calling `ScriptedReceiver([first, again])`.
- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(receiver), RecordingSender(), lambda _view: Action.KEEP).run()`.
- Checks that `(report.kept, again.settled, receiver.closed)` equals `(1, ['abandon'], 1)`.

**Lines 91 to 94**

```python
def test_an_empty_dead_letter_queue_is_a_clean_no_op():
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([])), RecordingSender(), lambda _view: Action.FIX).run()
    assert (report.fixed, report.dropped, report.kept) == (0, 0, 0)
    assert ReplayDeadLetters(FakeInbox(), RecordingSender(), lambda _view: Action.FIX).run().fixed == 0
```

**Function `test_an_empty_dead_letter_queue_is_a_clean_no_op`** takes no parameters.

What happens, step by step:

- Sets `report` to the result of calling `ReplayDeadLetters(FakeInbox(ScriptedReceiver([])), RecordingSender(), lambda _view: Action.FIX).run()`.
- Checks that `(report.fixed, report.dropped, report.kept)` equals `(0, 0, 0)`.
- Checks that `ReplayDeadLetters(FakeInbox(), RecordingSender(), lambda _view: Action.FIX).run().fixed` equals `0`.

**Lines 97 to 98**

```python
def _row(order, customer, seq, cents=1000, count=1, apply_order=0):
    return OrderRow(apply_order, order, customer, seq, cents, count)
```

**Function `_row`** takes `order`, `customer`, `seq`, `cents`, default `1000`, `count`, default `1`, `apply_order`, default `0`.

What happens, step by step:

- Returns `OrderRow(apply_order, order, customer, seq, cents, count)`.

**Line 101**

```python
class _Reader:
```

**Class `_Reader`**.

**Lines 102 to 103**

```python
    def __init__(self, rows):
        self._rows = rows
```

**Method `__init__`** takes `rows`.

What happens, step by step:

- Sets `self._rows` to `rows`.

**Lines 105 to 106**

```python
    def rows(self):
        return self._rows
```

**Method `rows`** takes no parameters.

What happens, step by step:

- Returns `self._rows`.

**Lines 109 to 115**

```python
def _perfect(per_customer=3, customers=("c01", "c02")):
    rows, order = [], 0
    for seq in range(1, per_customer + 1):
        for customer in customers:
            order += 1
            rows.append(_row(f"o-{customer}-{seq}", customer, seq, apply_order=order))
    return rows
```

**Function `_perfect`** takes `per_customer`, default `3`, `customers`, default `('c01', 'c02')`.

What happens, step by step:

- Sets `(rows, order)` to `([], 0)`.
- For each `seq` in `range(1, per_customer + 1)`:
  - For each `customer` in `customers`:
    - Updates `order` with `=` `1`.
    - Calls `rows.append(_row(f'o-{customer}-{seq}', customer, seq, apply_order=order))`.
- Returns `rows`.

Names used here:

- `range(n)` is the whole numbers `0` up to but not including `n`.

**Lines 118 to 120**

```python
def test_a_perfect_ledger_has_no_problems():
    checker = CheckLedger(_Reader(_perfect()))
    assert checker.problems(expected_rows=6, expected_total_cents=6000, per_customer=3) == []
```

**Function `test_a_perfect_ledger_has_no_problems`** takes no parameters.

What happens, step by step:

- Sets `checker` to the result of calling `CheckLedger(_Reader(_perfect()))`.
- Checks that `checker.problems(expected_rows=6, expected_total_cents=6000, per_customer=3)` equals `[]`.

Names used here:

- `problems` is the repository's own: The differences from the expected end state; an empty list means the ledger is exactly right (defined in `src/order_worker/application/check_ledger.py`)

**Lines 123 to 128**

```python
def test_a_duplicate_effect_is_reported_with_the_wrong_count_and_total():
    rows = [*_perfect(), _row("o-c01-2", "c01", 2, apply_order=7)]
    problems = CheckLedger(_Reader(rows)).problems(6, 6000, per_customer=3)
    assert "expected 6 rows, found 7" in problems
    assert "expected a total of 60.0, found 70.0" in problems
    assert "duplicate effect for order o-c01-2" in problems
```

**Function `test_a_duplicate_effect_is_reported_with_the_wrong_count_and_total`** takes no parameters.

**New idea.** `*items` in a call or list spreads the elements of `items` out as separate values; `**mapping` spreads a dictionary out as named arguments.

What happens, step by step:

- Sets `rows` to `[*_perfect(), _row('o-c01-2', 'c01', 2, apply_order=7)]`.
- Sets `problems` to the result of calling `CheckLedger(_Reader(rows)).problems(6, 6000, per_customer=3)`.
- Checks that `'expected 6 rows, found 7'` is one of / is inside `problems`.
- Checks that `'expected a total of 60.0, found 70.0'` is one of / is inside `problems`.
- Checks that `'duplicate effect for order o-c01-2'` is one of / is inside `problems`.

**Lines 131 to 138**

```python
def test_a_row_applied_after_a_higher_sequence_is_reported_out_of_order():
    rows = [
        _row("o-a", "c01", 1, apply_order=1),
        _row("o-c", "c01", 3, apply_order=2),
        _row("o-b", "c01", 2, apply_order=3),
    ]
    problems = CheckLedger(_Reader(rows)).problems(3, 3000, per_customer=3)
    assert problems == ["out of order: c01: seq 2 applied after seq 3"]
```

**Function `test_a_row_applied_after_a_higher_sequence_is_reported_out_of_order`** takes no parameters.

What happens, step by step:

- Sets `rows` to `[_row('o-a', 'c01', 1, apply_order=1), _row('o-c', 'c01', 3, apply_order=2), _row('o-b', 'c01', 2, apply_orde…` (long; see the quote).
- Sets `problems` to the result of calling `CheckLedger(_Reader(rows)).problems(3, 3000, per_customer=3)`.
- Checks that `problems` equals `['out of order: c01: seq 2 applied after seq 3']`.

**Lines 141 to 144**

```python
def test_a_missing_sequence_number_is_reported():
    rows = [_row("o-a", "c01", 1, apply_order=1), _row("o-c", "c01", 3, apply_order=2)]
    problems = CheckLedger(_Reader(rows)).problems(2, 2000, per_customer=3)
    assert problems == ["c01: missing [2]"]
```

**Function `test_a_missing_sequence_number_is_reported`** takes no parameters.

What happens, step by step:

- Sets `rows` to `[_row('o-a', 'c01', 1, apply_order=1), _row('o-c', 'c01', 3, apply_order=2)]`.
- Sets `problems` to the result of calling `CheckLedger(_Reader(rows)).problems(2, 2000, per_customer=3)`.
- Checks that `problems` equals `['c01: missing [2]']`.

**Lines 147 to 148**

```python
def test_the_total_is_reported_in_currency_units():
    assert CheckLedger(_Reader(_perfect())).report(3).total == 60.0
```

**Function `test_the_total_is_reported_in_currency_units`** takes no parameters.

What happens, step by step:

- Checks that `CheckLedger(_Reader(_perfect())).report(3).total` equals `60.0`.

Names used here:

- `report` is the repository's own: Summarize the ledger: duplicates, per-customer order violations and gaps in 1..`per_customer` (defined in `src/order_worker/application/check_ledger.py`)

#### `tests/unit/application/test_run_worker.py`

84 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 2**

```python
import contextlib
import json
```

What happens, step by step:

- `contextlib`: the standard-library module of context-manager helpers.
- `json`: the standard-library module for JSON.

**Lines 4 to 6**

```python
from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.run_worker import RunWorker
from tests.unit.application.fakes import FakeClock, FakeDelivery, FakeInbox, FakeLedger, ScriptedReceiver
```

What happens, step by step:

- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `RunWorker` from the repository's own module `order_worker.application.run_worker`: Receive until told to stop, until idle for a while, or until a message budget is spent (defined in `src/order_worker/application/run_worker.py`)
- `FakeClock` from the test helper module `tests.unit.application.fakes`: no description in the code (defined in `tests/unit/application/fakes.py`).
- `FakeDelivery` from the test helper module `tests.unit.application.fakes`: A delivery that records how it was settled, in order, with the other fakes' events (defined in `tests/unit/application/fakes.py`).
- `FakeInbox` from the test helper module `tests.unit.application.fakes`: Opens the scripted receivers in turn; None when they run out (defined in `tests/unit/application/fakes.py`).
- `FakeLedger` from the test helper module `tests.unit.application.fakes`: Records applies; can be told to raise, or to report a duplicate or a previous sequence (defined in `tests/unit/application/fakes.py`).
- `ScriptedReceiver` from the test helper module `tests.unit.application.fakes`: Yields the scripted deliveries, then None; counts closes (defined in `tests/unit/application/fakes.py`).

**Lines 9 to 11**

```python
def _delivery(seq: int, message_id: str | None = None) -> FakeDelivery:
    body = json.dumps({"orderId": f"o-{seq}", "customerId": "c01", "seq": seq, "amount": 10.0}).encode()
    return FakeDelivery(body, message_id=message_id or f"m-{seq}")
```

**Function `_delivery`** takes `seq` (type `int`), `message_id` (type `str | None`), default `None`; gives back `FakeDelivery`.

What happens, step by step:

- Sets `body` to the result of calling `json.dumps({'orderId': f'o-{seq}', 'customerId': 'c01', 'seq': seq, 'amount': 10.0}).encode()`.
- Returns `FakeDelivery(body, message_id=message_id or f'm-{seq}')`.

**Lines 14 to 17**

```python
def _worker(inbox, clock=None, heartbeat=None):
    clock = clock or FakeClock()
    kwargs = {"heartbeat": heartbeat} if heartbeat else {}
    return RunWorker(inbox, HandleDelivery(FakeLedger(), clock), clock, max_wait_seconds=10.0, **kwargs)
```

**Function `_worker`** takes `inbox`, `clock`, default `None`, `heartbeat`, default `None`.

What happens, step by step:

- Sets `clock` to `clock or FakeClock()`.
- Sets `kwargs` to `{'heartbeat': heartbeat} if heartbeat else {}`.
- Returns `RunWorker(inbox, HandleDelivery(FakeLedger(), clock), clock, max_wait_seconds=10.0, **kwargs)`.

**Lines 20 to 24**

```python
def test_it_handles_every_delivery_and_counts_the_effects():
    clock = FakeClock()
    receiver = ScriptedReceiver([_delivery(1), _delivery(2), _delivery(2, "m-2")], clock)
    stats = _worker(FakeInbox(receiver), clock).run(until_idle_seconds=5)
    assert (stats.received, stats.applied, stats.skipped_duplicates) == (3, 2, 1)
```

**Function `test_it_handles_every_delivery_and_counts_the_effects`** takes no parameters.

What happens, step by step:

- Sets `clock` to the result of calling `FakeClock()`.
- Sets `receiver` to the result of calling `ScriptedReceiver([_delivery(1), _delivery(2), _delivery(2, 'm-2')], clock)`.
- Sets `stats` to the result of calling `_worker(FakeInbox(receiver), clock).run(until_idle_seconds=5)`.
- Checks that `(stats.received, stats.applied, stats.skipped_duplicates)` equals `(3, 2, 1)`.

**Lines 27 to 32**

```python
def test_it_stops_after_the_idle_period_with_no_messages():
    clock = FakeClock()
    inbox = FakeInbox(*[ScriptedReceiver([], clock) for _ in range(10)])
    stats = _worker(inbox, clock).run(until_idle_seconds=25)
    assert stats.received == 0
    assert 25 <= clock.time < 45  # three empty passes of 10 s each
```

**Function `test_it_stops_after_the_idle_period_with_no_messages`** takes no parameters.

**New idea.** `a < b < c` is a chained comparison: true when both `a < b` and `b < c` hold.

What happens, step by step:

- Sets `clock` to the result of calling `FakeClock()`.
- Sets `inbox` to the result of calling `FakeInbox(*[ScriptedReceiver([], clock) for _ in range(10)])`.
- Sets `stats` to the result of calling `_worker(inbox, clock).run(until_idle_seconds=25)`.
- Checks that `stats.received` equals `0`.
- Checks that `25` is at most `clock.time` is less than `45`.

**Lines 35 to 46**

```python
def test_receiving_a_message_resets_the_idle_clock():
    clock = FakeClock()
    inbox = FakeInbox(
        ScriptedReceiver([], clock),
        ScriptedReceiver([_delivery(1)], clock),
        ScriptedReceiver([], clock),
        ScriptedReceiver([], clock),
    )
    stats = _worker(inbox, clock).run(until_idle_seconds=15)
    assert stats.received == 1
    assert inbox.opened == 5  # the fifth open finds no receiver and waits instead of spinning
    assert clock.time >= 35
```

**Function `test_receiving_a_message_resets_the_idle_clock`** takes no parameters.

What happens, step by step:

- Sets `clock` to the result of calling `FakeClock()`.
- Sets `inbox` to the result of calling `FakeInbox` with `ScriptedReceiver([], clock)`; `ScriptedReceiver([_delivery(1)], clock)`; `ScriptedReceiver([], clock)`; `ScriptedReceiver([], clock)`.
- Sets `stats` to the result of calling `_worker(inbox, clock).run(until_idle_seconds=15)`.
- Checks that `stats.received` equals `1`.
- Checks that `inbox.opened` equals `5`.
- Checks that `clock.time` is at least `35`.

**Lines 49 to 53**

```python
def test_it_stops_after_the_message_budget():
    receiver = ScriptedReceiver([_delivery(n) for n in range(1, 6)])
    stats = _worker(FakeInbox(receiver)).run(max_messages=3)
    assert stats.received == 3
    assert receiver.closed == 1
```

**Function `test_it_stops_after_the_message_budget`** takes no parameters.

What happens, step by step:

- Sets `receiver` to the result of calling `ScriptedReceiver([_delivery(n) for n in range(1, 6)])`.
- Sets `stats` to the result of calling `_worker(FakeInbox(receiver)).run(max_messages=3)`.
- Checks that `stats.received` equals `3`.
- Checks that `receiver.closed` equals `1`.

**Lines 56 to 70**

```python
def test_a_shutdown_request_finishes_the_message_in_hand_then_closes_the_receiver():
    receiver = ScriptedReceiver([_delivery(1), _delivery(2), _delivery(3)])
    stop = {"now": False}
    delivery_two = receiver._deliveries[1]
    original = delivery_two.complete

    def complete_then_stop() -> None:
        original()
        stop["now"] = True  # the signal arrives while message 2 is being settled

    delivery_two.complete = complete_then_stop  # type: ignore[method-assign]
    stats = _worker(FakeInbox(receiver)).run(should_stop=lambda: stop["now"])
    assert stats.received == 2
    assert delivery_two.settled == ["complete"]
    assert receiver.closed == 1
```

**Function `test_a_shutdown_request_finishes_the_message_in_hand_then_closes_the_receiver`** takes no parameters.

What happens, step by step:

- Sets `receiver` to the result of calling `ScriptedReceiver([_delivery(1), _delivery(2), _delivery(3)])`.
- Sets `stop` to `{'now': False}`.
- Sets `delivery_two` to `receiver._deliveries[1]`.
- Sets `original` to `delivery_two.complete`.
- Defines the inner function `complete_then_stop()`:
  - Calls `original()`.
  - Sets `stop['now']` to `True`.
- Sets `delivery_two.complete` to `complete_then_stop`.
- Sets `stats` to the result of calling `_worker(FakeInbox(receiver)).run(should_stop=lambda: stop['now'])`.
- Checks that `stats.received` equals `2`.
- Checks that `delivery_two.settled` equals `['complete']`.
- Checks that `receiver.closed` equals `1`.

**Lines 73 to 83**

```python
def test_the_receiver_is_closed_even_when_handling_raises():
    class Boom(FakeLedger):
        def apply(self, *args, **kwargs):
            raise RuntimeError("process killed")

    receiver = ScriptedReceiver([_delivery(1)])
    clock = FakeClock()
    worker = RunWorker(FakeInbox(receiver), HandleDelivery(Boom(), clock), clock)
    with contextlib.suppress(RuntimeError):
        worker.run(max_messages=1)
    assert receiver.closed == 1
```

**Function `test_the_receiver_is_closed_even_when_handling_raises`** takes no parameters.

What happens, step by step:

- Defines the class `Boom`.
- Sets `receiver` to the result of calling `ScriptedReceiver([_delivery(1)])`.
- Sets `clock` to the result of calling `FakeClock()`.
- Sets `worker` to the result of calling `RunWorker(FakeInbox(receiver), HandleDelivery(Boom(), clock), clock)`.
- Inside a block that `contextlib.suppress(RuntimeError)`:
  - Calls `worker.run(max_messages=1)`.
- Checks that `receiver.closed` equals `1`.

**Lines 86 to 90**

```python
def test_it_beats_the_heart_on_every_pass_and_every_message():
    beats: list[int] = []
    receiver = ScriptedReceiver([_delivery(1), _delivery(2)])
    _worker(FakeInbox(receiver), heartbeat=lambda: beats.append(1)).run(max_messages=2)
    assert len(beats) >= 3
```

**Function `test_it_beats_the_heart_on_every_pass_and_every_message`** takes no parameters.

What happens, step by step:

- Sets `beats` with type `list[int]` and starting value `[]`.
- Sets `receiver` to the result of calling `ScriptedReceiver([_delivery(1), _delivery(2)])`.
- Calls `_worker(FakeInbox(receiver), heartbeat=lambda: beats.append(1)).run(max_messages=2)`.
- Checks that `len(beats)` is at least `3`.

**Lines 93 to 97**

```python
def test_a_lost_lock_is_counted():
    lost = _delivery(1)
    lost.lock_lost = True
    stats = _worker(FakeInbox(ScriptedReceiver([lost]))).run(max_messages=1)
    assert (stats.applied, stats.lock_lost) == (1, 1)
```

**Function `test_a_lost_lock_is_counted`** takes no parameters.

What happens, step by step:

- Sets `lost` to the result of calling `_delivery(1)`.
- Sets `lost.lock_lost` to `True`.
- Sets `stats` to the result of calling `_worker(FakeInbox(ScriptedReceiver([lost]))).run(max_messages=1)`.
- Checks that `(stats.applied, stats.lock_lost)` equals `(1, 1)`.

**Lines 100 to 105**

```python
def test_dead_lettered_and_abandoned_deliveries_are_counted():
    bad = FakeDelivery(b"not json", message_id="bad")
    ledger = FakeLedger()
    clock = FakeClock()
    worker = RunWorker(FakeInbox(ScriptedReceiver([bad])), HandleDelivery(ledger, clock), clock)
    assert worker.run(max_messages=1).dead_lettered == 1
```

**Function `test_dead_lettered_and_abandoned_deliveries_are_counted`** takes no parameters.

**New idea.** `bytes` is raw binary data (`b"..."`), as opposed to `str`, which is text. `text.encode("utf-8")` turns text into bytes and `data.decode("utf-8")` turns bytes back into text.

What happens, step by step:

- Sets `bad` to the result of calling `FakeDelivery(b'not json', message_id='bad')`.
- Sets `ledger` to the result of calling `FakeLedger()`.
- Sets `clock` to the result of calling `FakeClock()`.
- Sets `worker` to the result of calling `RunWorker(FakeInbox(ScriptedReceiver([bad])), HandleDelivery(ledger, clock), clock)`.
- Checks that `worker.run(max_messages=1).dead_lettered` equals `1`.

**Lines 108 to 112**

```python
def test_when_no_receiver_can_be_opened_it_waits_instead_of_spinning():
    clock = FakeClock()
    stats = _worker(FakeInbox(), clock).run(until_idle_seconds=25)
    assert stats.received == 0
    assert clock.slept == [10.0, 10.0, 10.0, 10.0]
```

**Function `test_when_no_receiver_can_be_opened_it_waits_instead_of_spinning`** takes no parameters.

What happens, step by step:

- Sets `clock` to the result of calling `FakeClock()`.
- Sets `stats` to the result of calling `_worker(FakeInbox(), clock).run(until_idle_seconds=25)`.
- Checks that `stats.received` equals `0`.
- Checks that `clock.slept` equals `[10.0, 10.0, 10.0, 10.0]`.

#### `tests/unit/domain/test_commands_ordering_and_repair.py`

77 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
import json
```

What happens, step by step:

- `json`: the standard-library module for JSON.

**Line 3**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 5 to 9**

```python
from order_worker.domain.commands import POISON_BODY, OrderCommand, known_commands, parse_command
from order_worker.domain.errors import InvalidCommandError
from order_worker.domain.ordering import is_next_in_sequence
from order_worker.domain.processing import Chaos
from order_worker.domain.repair import DEFAULT_AMOUNT, repair_body
```

What happens, step by step:

- `POISON_BODY` from the repository's own module `order_worker.domain.commands`.
- `OrderCommand` from the repository's own module `order_worker.domain.commands`: One order: who ordered, which order, the customer's sequence number and the amount in cents (defined in `src/order_worker/domain/commands.py`)
- `known_commands` from the repository's own module `order_worker.domain.commands`: The lesson's producer set: `per_customer` commands for each of `customers`, sequence-major, so a customer's commands are far apart in the queue and any reordering shows up as a gap in the sequence (defined in `src/order_worker/domain/commands.py`)
- `parse_command` from the repository's own module `order_worker.domain.commands`: Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show (defined in `src/order_worker/domain/commands.py`)
- `InvalidCommandError` from the repository's own module `order_worker.domain.errors`: The message body is not a valid order command (defined in `src/order_worker/domain/errors.py`)
- `is_next_in_sequence` from the repository's own module `order_worker.domain.ordering`: True when `seq` follows the customer's last applied sequence number (0 when nothing was applied yet) (defined in `src/order_worker/domain/ordering.py`)
- `Chaos` from the repository's own module `order_worker.domain.processing`: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit (defined in `src/order_worker/domain/processing.py`)
- `DEFAULT_AMOUNT` from the repository's own module `order_worker.domain.repair`.
- `repair_body` from the repository's own module `order_worker.domain.repair`: Return a corrected body for a dead letter with this `reason`, or raise `InvalidCommandError` if none is known (defined in `src/order_worker/domain/repair.py`)

**Lines 12 to 14**

```python
def _body(**overrides):
    payload = {"orderId": "o-c01-001", "customerId": "c01", "seq": 1, "amount": 10.0}
    return json.dumps({**payload, **overrides})
```

**Function `_body`** takes `**overrides` (all extra named values).

What happens, step by step:

- Sets `payload` to `{'orderId': 'o-c01-001', 'customerId': 'c01', 'seq': 1, 'amount': 10.0}`.
- Returns `json.dumps({**payload, **overrides})`.

**Lines 17 to 18**

```python
def test_a_valid_command_is_parsed_with_its_amount_in_cents():
    assert parse_command(_body()) == OrderCommand("o-c01-001", "c01", 1, 1000)
```

**Function `test_a_valid_command_is_parsed_with_its_amount_in_cents`** takes no parameters.

What happens, step by step:

- Checks that `parse_command(_body())` equals `OrderCommand('o-c01-001', 'c01', 1, 1000)`.

**Lines 21 to 23**

```python
def test_a_command_survives_the_round_trip_through_json():
    command = OrderCommand("o-c02-007", "c02", 7, 1234)
    assert parse_command(command.to_json()) == command
```

**Function `test_a_command_survives_the_round_trip_through_json`** takes no parameters.

What happens, step by step:

- Sets `command` to the result of calling `OrderCommand('o-c02-007', 'c02', 7, 1234)`.
- Checks that `parse_command(command.to_json())` equals `command`.

Names used here:

- `to_json` is the repository's own: Render the command the way the producer sends it: the amount as a decimal number of currency units (defined in `src/order_worker/domain/commands.py`)

**Lines 26 to 28**

```python
@pytest.mark.parametrize("amount", ["19.99", 19.99, 20, "0.01"])
def test_amounts_with_at_most_two_decimals_are_accepted(amount):
    assert parse_command(_body(amount=amount)).amount_cents == round(float(amount) * 100)
```

**Function `test_amounts_with_at_most_two_decimals_are_accepted`** takes `amount`.

**New idea.** `@pytest.mark.parametrize("names", [values...])` is a **decorator** that runs the same test function once for each listed value set. Each run is reported separately, and the values arrive as the function's parameters.

What happens, step by step:

- Decorator `@pytest.mark.parametrize('amount', ['19.99', 19.99, 20, '0.01'])`.
- Checks that `parse_command(_body(amount=amount)).amount_cents` equals `round(float(amount) * 100)`.

Names used here:

- `round(x, n)` rounds to `n` decimal places.
- `float(x)` turns a value into a decimal number.

**Lines 31 to 35**

```python
@pytest.mark.parametrize("amount", ["abc", None, True, [], "NaN", "Infinity", 0, -5, "1.005", "", {}])
def test_an_amount_that_is_not_a_positive_number_with_two_decimals_is_invalid_amount(amount):
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(_body(amount=amount))
    assert caught.value.reason == "InvalidAmount"
```

**Function `test_an_amount_that_is_not_a_positive_number_with_two_decimals_is_invalid_amount`** takes `amount`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize('amount', ['abc', None, True, [], 'NaN', 'Infinity', 0, -5, '1.005', '', {}])`.
- Inside a block that expects an error: `pytest.raises(InvalidCommandError)`:
  - Calls `parse_command(_body(amount=amount))`.
- Checks that `caught.value.reason` equals `'InvalidAmount'`.

**Lines 38 to 57**

```python
@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        "[]",
        "42",
        _body(orderId=""),
        _body(customerId="has space"),
        _body(seq=0),
        _body(seq="1"),
        _body(seq=True),
        _body(seq=1.5),
        _body(orderId=None),
    ],
)
def test_a_body_with_the_wrong_shape_is_malformed(body):
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(body)
    assert caught.value.reason == "MalformedCommand"
```

**Function `test_a_body_with_the_wrong_shape_is_malformed`** takes `body`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize('body', [b'not json', b'\xff\xfe', '[]', '42', _body(orderId=''), _body(customerId='has space'), _body(seq=0), _body(seq='1'), _body(seq=True), _body(seq=1.5), _body(orderId=None)])`.
- Inside a block that expects an error: `pytest.raises(InvalidCommandError)`:
  - Calls `parse_command(body)`.
- Checks that `caught.value.reason` equals `'MalformedCommand'`.

**Lines 60 to 66**

```python
def test_the_known_set_has_twenty_customers_with_fifty_commands_in_sequence_major_order():
    commands = list(known_commands())
    assert len(commands) == 1000
    assert sum(command.amount_cents for command in commands) == 1_000_000
    assert [command.customer_id for command in commands[:3]] == ["c01", "c02", "c03"]
    assert commands[20].order_id == "o-c01-002"  # a customer's next command is 20 messages later
    assert len({command.order_id for command in commands}) == 1000
```

**Function `test_the_known_set_has_twenty_customers_with_fifty_commands_in_sequence_major_order`** takes no parameters.

What happens, step by step:

- Sets `commands` to the result of calling `list(known_commands())`.
- Checks that `len(commands)` equals `1000`.
- Checks that `sum((command.amount_cents for command in commands))` equals `1000000`.
- Checks that `[command.customer_id for command in commands[:3]]` equals `['c01', 'c02', 'c03']`.
- Checks that `commands[20].order_id` equals `'o-c01-002'`.
- Checks that `len({command.order_id for command in commands})` equals `1000`.

Names used here:

- `sum(x)` adds the numbers.

**Lines 69 to 72**

```python
def test_the_poison_command_always_fails_validation_with_the_lessons_reason():
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(POISON_BODY)
    assert (caught.value.reason, caught.value.description) == ("InvalidAmount", "amount is not a number")
```

**Function `test_the_poison_command_always_fails_validation_with_the_lessons_reason`** takes no parameters.

What happens, step by step:

- Inside a block that expects an error: `pytest.raises(InvalidCommandError)`:
  - Calls `parse_command(POISON_BODY)`.
- Checks that `(caught.value.reason, caught.value.description)` equals `('InvalidAmount', 'amount is not a number')`.

**Lines 75 to 79**

```python
@pytest.mark.parametrize(
    ("last", "seq", "expected"), [(0, 1, True), (4, 5, True), (4, 6, False), (4, 3, False), (4, 4, False)]
)
def test_a_command_is_in_order_only_when_it_follows_the_last_applied_sequence(last, seq, expected):
    assert is_next_in_sequence(last, seq) is expected
```

**Function `test_a_command_is_in_order_only_when_it_follows_the_last_applied_sequence`** takes `last`, `seq`, `expected`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize(('last', 'seq', 'expected'), [(0, 1, True), (4, 5, True), (4, 6, False), (4, 3, False), (4, 4, False)])`.
- Checks that `is_next_in_sequence(last, seq)` is exactly `expected`.

**Lines 82 to 87**

```python
def test_chaos_slows_only_the_first_delivery_of_every_tenth_sequence():
    chaos = Chaos(slow_every=10)
    assert chaos.delays(10, 1)
    assert chaos.delays(50, 1)
    assert not chaos.delays(10, 2)  # the retry must not be slow too
    assert not chaos.delays(11, 1)
```

**Function `test_chaos_slows_only_the_first_delivery_of_every_tenth_sequence`** takes no parameters.

What happens, step by step:

- Sets `chaos` to the result of calling `Chaos(slow_every=10)`.
- Checks that `chaos.delays(10, 1)` is true.
- Checks that `chaos.delays(50, 1)` is true.
- Checks that it is not the case that `chaos.delays(10, 2)` is true.
- Checks that it is not the case that `chaos.delays(11, 1)` is true.

Names used here:

- `delays` is the repository's own: True when this delivery is the one to slow down (defined in `src/order_worker/domain/processing.py`)

**Lines 90 to 91**

```python
def test_chaos_is_off_by_default():
    assert not Chaos().delays(10, 1)
```

**Function `test_chaos_is_off_by_default`** takes no parameters.

What happens, step by step:

- Checks that it is not the case that `Chaos().delays(10, 1)` is true.

**Lines 94 to 96**

```python
def test_an_invalid_amount_is_repaired_with_the_default_and_every_other_field_is_kept():
    repaired = json.loads(repair_body(POISON_BODY, "InvalidAmount"))
    assert repaired == {"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": DEFAULT_AMOUNT}
```

**Function `test_an_invalid_amount_is_repaired_with_the_default_and_every_other_field_is_kept`** takes no parameters.

What happens, step by step:

- Sets `repaired` to the result of calling `json.loads(repair_body(POISON_BODY, 'InvalidAmount'))`.
- Checks that `repaired` equals `{'orderId': 'o-bad', 'customerId': 'c07', 'seq': 51, 'amount': DEFAULT_AMOUNT}`.

**Lines 99 to 105**

```python
@pytest.mark.parametrize(
    ("body", "reason"), [(POISON_BODY, "UnknownCustomer"), ("not json", "InvalidAmount"), ("[]", "InvalidAmount")]
)
def test_a_dead_letter_without_a_known_repair_is_refused(body, reason):
    with pytest.raises(InvalidCommandError) as caught:
        repair_body(body, reason)
    assert caught.value.reason == "NoKnownRepair"
```

**Function `test_a_dead_letter_without_a_known_repair_is_refused`** takes `body`, `reason`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize(('body', 'reason'), [(POISON_BODY, 'UnknownCustomer'), ('not json', 'InvalidAmount'), ('[]', 'InvalidAmount')])`.
- Inside a block that expects an error: `pytest.raises(InvalidCommandError)`:
  - Calls `repair_body(body, reason)`.
- Checks that `caught.value.reason` equals `'NoKnownRepair'`.

#### `tests/unit/infrastructure/test_servicebus_adapter.py`

184 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The Service Bus adapter against stubs of the SDK objects: the calls it makes and the errors it translates."""
```

**New idea.** An **SDK** (software development kit) or *client library* is a package of ready-made code that talks to a service for you. The Azure ones turn calls such as "read this secret" into the correct web requests, add the access token and retry transient failures.

The module docstring says: The Service Bus adapter against stubs of the SDK objects: the calls it makes and the errors it translates.

**Lines 3 to 4**

```python
from types import SimpleNamespace
from typing import Any
```

What happens, step by step:

- `SimpleNamespace` from `types`: a plain object whose attributes are set from keywords.
- `Any` from `typing`: the type hint that allows any value.

**Lines 6 to 13**

```python
import pytest
from azure.servicebus import NEXT_AVAILABLE_SESSION, ServiceBusSubQueue
from azure.servicebus.exceptions import (
    MessageLockLostError,
    OperationTimeoutError,
    ServiceBusConnectionError,
    SessionLockLostError,
)
```

What happens, step by step:

- `pytest`: the test framework.
- `NEXT_AVAILABLE_SESSION` from `azure.servicebus`: a constant meaning "give me whichever session has messages".
- `ServiceBusSubQueue` from `azure.servicebus`: names the sub-queues of a queue (the dead-letter queue).
- `MessageLockLostError` from `azure.servicebus.exceptions`: raised when a message's lock expired before it was settled.
- `OperationTimeoutError` from `azure.servicebus.exceptions`: raised when a Service Bus operation took too long.
- `ServiceBusConnectionError` from `azure.servicebus.exceptions`: raised when the connection was lost.
- `SessionLockLostError` from `azure.servicebus.exceptions`: raised when a session's lock expired.

**Lines 15 to 19**

```python
from order_worker.application.ports import OutgoingMessage
from order_worker.domain.errors import LockLostError
from order_worker.infrastructure.servicebus import ServiceBusMessaging, _SdkDelivery, _SdkReceiver
from order_worker.infrastructure.settings import ConfigError, Settings
from order_worker.infrastructure.wiring import connect
```

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)
- `ServiceBusMessaging` from the repository's own module `order_worker.infrastructure.servicebus`: One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue (defined in `src/order_worker/infrastructure/servicebus.py`)
- `_SdkDelivery` from the repository's own module `order_worker.infrastructure.servicebus`: A received message and the receiver that holds its lock (defined in `src/order_worker/infrastructure/servicebus.py`)
- `_SdkReceiver` from the repository's own module `order_worker.infrastructure.servicebus`: no description in the code (defined in `src/order_worker/infrastructure/servicebus.py`)
- `ConfigError` from the repository's own module `order_worker.infrastructure.settings`: One or more settings are missing or malformed; the message lists all of them (defined in `src/order_worker/infrastructure/settings.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `connect` from the repository's own module `order_worker.infrastructure.wiring`: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)

**Line 22**

```python
class _Credential:
```

**Class `_Credential`**.

**Lines 23 to 24**

```python
    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        raise AssertionError("no network in unit tests")
```

**Method `get_token`** takes `*scopes` (all extra positional values), `**kwargs` (all extra named values); gives back `Any`.

What happens, step by step:

- Raises `AssertionError('no network in unit tests')`.

Names used here:

- `AssertionError` is what a failed `assert` raises.

**Line 27**

```python
class _SdkReceiverStub:
```

**Class `_SdkReceiverStub`**.

**Lines 28 to 32**

```python
    def __init__(self, messages=(), error=None) -> None:
        self.messages = list(messages)
        self.error = error
        self.calls: list[tuple[str, Any]] = []
        self.closed = False
```

**Method `__init__`** takes `messages`, default `()`, `error`, default `None`; gives back `None`.

What happens, step by step:

- Sets `self.messages` to the result of calling `list(messages)`.
- Sets `self.error` to `error`.
- Sets `self.calls` with type `list[tuple[str, Any]]` and starting value `[]`.
- Sets `self.closed` to `False`.

**Lines 34 to 38**

```python
    def receive_messages(self, max_message_count, max_wait_time):
        self.calls.append(("receive", (max_message_count, max_wait_time)))
        if self.error:
            raise self.error
        return [self.messages.pop(0)] if self.messages else []
```

**Method `receive_messages`** takes `max_message_count`, `max_wait_time`.

What happens, step by step:

- Calls `self.calls.append(('receive', (max_message_count, max_wait_time)))`.
- If `self.error` is true:
  - Raises `self.error`.
- Returns `[self.messages.pop(0)] if self.messages else []`.

**Lines 40 to 43**

```python
    def complete_message(self, message):
        self.calls.append(("complete", message))
        if self.error:
            raise self.error
```

**Method `complete_message`** takes `message`.

What happens, step by step:

- Calls `self.calls.append(('complete', message))`.
- If `self.error` is true:
  - Raises `self.error`.

**Lines 45 to 48**

```python
    def abandon_message(self, message):
        self.calls.append(("abandon", message))
        if self.error:
            raise self.error
```

**Method `abandon_message`** takes `message`.

What happens, step by step:

- Calls `self.calls.append(('abandon', message))`.
- If `self.error` is true:
  - Raises `self.error`.

**Lines 50 to 53**

```python
    def dead_letter_message(self, message, reason, error_description):
        self.calls.append(("dead_letter", (reason, error_description)))
        if self.error:
            raise self.error
```

**Method `dead_letter_message`** takes `message`, `reason`, `error_description`.

What happens, step by step:

- Calls `self.calls.append(('dead_letter', (reason, error_description)))`.
- If `self.error` is true:
  - Raises `self.error`.

**Lines 55 to 56**

```python
    def close(self):
        self.closed = True
```

**Method `close`** takes no parameters.

What happens, step by step:

- Sets `self.closed` to `True`.

**Lines 59 to 68**

```python
def _message(**kwargs):
    defaults = {
        "message_id": "o-1",
        "body": iter([b'{"a":', b"1}"]),
        "delivery_count": 2,
        "session_id": "c01",
        "dead_letter_reason": "InvalidAmount",
        "dead_letter_error_description": "amount is not a number",
    }
    return SimpleNamespace(**{**defaults, **kwargs})
```

**Function `_message`** takes `**kwargs` (all extra named values).

What happens, step by step:

- Sets `defaults` to `{'message_id': 'o-1', 'body': iter([b'{"a":', b'1}']), 'delivery_count': 2, 'session_id': 'c01', 'dead_letter…` (long; see the quote).
- Returns `SimpleNamespace(**{**defaults, **kwargs})`.

Names used here:

- `iter(x)` makes an iterator, an object that hands out items one at a time with `next`.

**Lines 71 to 79**

```python
def test_a_delivery_exposes_the_message_fields():
    delivery = _SdkDelivery(_SdkReceiverStub(), _message())  # type: ignore[arg-type]
    assert delivery.message_id == "o-1"
    assert delivery.body == b'{"a":1}'
    assert (delivery.delivery_count, delivery.session_id) == (2, "c01")
    assert (delivery.dead_letter_reason, delivery.dead_letter_description) == (
        "InvalidAmount",
        "amount is not a number",
    )
```

**Function `test_a_delivery_exposes_the_message_fields`** takes no parameters.

What happens, step by step:

- Sets `delivery` to the result of calling `_SdkDelivery(_SdkReceiverStub(), _message())`.
- Checks that `delivery.message_id` equals `'o-1'`.
- Checks that `delivery.body` equals `b'{"a":1}'`.
- Checks that `(delivery.delivery_count, delivery.session_id)` equals `(2, 'c01')`.
- Checks that `(delivery.dead_letter_reason, delivery.dead_letter_description)` equals `('InvalidAmount', 'amount is not a number')`.

**Lines 82 to 83**

```python
def test_a_missing_delivery_count_means_the_first_delivery():
    assert _SdkDelivery(_SdkReceiverStub(), _message(delivery_count=None)).delivery_count == 1  # type: ignore[arg-type]
```

**Function `test_a_missing_delivery_count_means_the_first_delivery`** takes no parameters.

What happens, step by step:

- Checks that `_SdkDelivery(_SdkReceiverStub(), _message(delivery_count=None)).delivery_count` equals `1`.

**Lines 86 to 96**

```python
def test_complete_abandon_and_dead_letter_call_the_receiver_with_the_message_and_the_reason():
    receiver, message = _SdkReceiverStub(), _message()
    delivery = _SdkDelivery(receiver, message)  # type: ignore[arg-type]
    delivery.complete()
    delivery.abandon()
    delivery.dead_letter("InvalidAmount", "amount is not a number")
    assert receiver.calls == [
        ("complete", message),
        ("abandon", message),
        ("dead_letter", ("InvalidAmount", "amount is not a number")),
    ]
```

**Function `test_complete_abandon_and_dead_letter_call_the_receiver_with_the_message_and_the_reason`** takes no parameters.

What happens, step by step:

- Sets `(receiver, message)` to `(_SdkReceiverStub(), _message())`.
- Sets `delivery` to the result of calling `_SdkDelivery(receiver, message)`.
- Calls `delivery.complete()`.
- Calls `delivery.abandon()`.
- Calls `delivery.dead_letter('InvalidAmount', 'amount is not a number')`.
- Checks that `receiver.calls` equals `[('complete', message), ('abandon', message), ('dead_letter', ('InvalidAmount', 'amount is not a number'))]`.

**Lines 99 to 112**

```python
@pytest.mark.parametrize(
    "error",
    [
        MessageLockLostError(message="x"),
        SessionLockLostError(message="x"),
        ServiceBusConnectionError(message="x"),
        OperationTimeoutError(message="x"),
    ],
)
def test_any_failure_that_leaves_the_message_unsettled_becomes_lock_lost(error):
    delivery = _SdkDelivery(_SdkReceiverStub(error=error), _message())  # type: ignore[arg-type]
    for action in (delivery.complete, delivery.abandon, lambda: delivery.dead_letter("r", "d")):
        with pytest.raises(LockLostError):
            action()
```

**Function `test_any_failure_that_leaves_the_message_unsettled_becomes_lock_lost`** takes `error`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize('error', [MessageLockLostError(message='x'), SessionLockLostError(message='x'), ServiceBusConnectionError(message='x'), OperationTimeoutError(message='x')])`.
- Sets `delivery` to the result of calling `_SdkDelivery(_SdkReceiverStub(error=error), _message())`.
- For each `action` in `(delivery.complete, delivery.abandon, lambda: delivery.dead_letter('r', 'd'))`:
  - Inside a block that expects an error: `pytest.raises(LockLostError)`:
    - Calls `action()`.

Names used here:

- `MessageLockLostError` means the lock on a message expired before it was settled.

**Lines 115 to 122**

```python
def test_the_receiver_asks_for_one_message_and_wraps_it():
    stub = _SdkReceiverStub([_message()])
    receiver = _SdkReceiver(stub, None)  # type: ignore[arg-type]
    delivery = receiver.receive(7)
    assert delivery is not None
    assert delivery.message_id == "o-1"
    assert stub.calls[0] == ("receive", (1, 7))
    assert receiver.receive(7) is None
```

**Function `test_the_receiver_asks_for_one_message_and_wraps_it`** takes no parameters.

What happens, step by step:

- Sets `stub` to the result of calling `_SdkReceiverStub([_message()])`.
- Sets `receiver` to the result of calling `_SdkReceiver(stub, None)`.
- Sets `delivery` to the result of calling `receiver.receive(7)`.
- Checks that `delivery` is not exactly `None`.
- Checks that `delivery.message_id` equals `'o-1'`.
- Checks that `stub.calls[0]` equals `('receive', (1, 7))`.
- Checks that `receiver.receive(7)` is exactly `None`.

**Lines 125 to 127**

```python
def test_a_session_receiver_with_no_session_to_lock_returns_none():
    receiver = _SdkReceiver(_SdkReceiverStub(error=OperationTimeoutError(message="no session")), None)  # type: ignore[arg-type]
    assert receiver.receive(1) is None
```

**Function `test_a_session_receiver_with_no_session_to_lock_returns_none`** takes no parameters.

What happens, step by step:

- Sets `receiver` to the result of calling `_SdkReceiver(_SdkReceiverStub(error=OperationTimeoutError(message='no session')), None)`.
- Checks that `receiver.receive(1)` is exactly `None`.

**Lines 130 to 136**

```python
def test_closing_the_receiver_closes_the_lock_renewer_too():
    closed = []
    renewer = SimpleNamespace(close=lambda: closed.append("renewer"))
    stub = _SdkReceiverStub()
    _SdkReceiver(stub, renewer).close()  # type: ignore[arg-type]
    assert stub.closed
    assert closed == ["renewer"]
```

**Function `test_closing_the_receiver_closes_the_lock_renewer_too`** takes no parameters.

What happens, step by step:

- Sets `closed` to `[]`.
- Sets `renewer` to the result of calling `SimpleNamespace(close=lambda: closed.append('renewer'))`.
- Sets `stub` to the result of calling `_SdkReceiverStub()`.
- Calls `_SdkReceiver(stub, renewer).close()`.
- Checks that `stub.closed` is true.
- Checks that `closed` equals `['renewer']`.

**Line 139**

```python
class _ClientStub:
```

**Class `_ClientStub`**.

**Lines 140 to 144**

```python
    def __init__(self) -> None:
        self.receivers: list[dict[str, Any]] = []
        self.sent: list[Any] = []
        self.batch_limit = 3
        self.closed = False
```

**Method `__init__`** takes no parameters; gives back `None`.

What happens, step by step:

- Sets `self.receivers` with type `list[dict[str, Any]]` and starting value `[]`.
- Sets `self.sent` with type `list[Any]` and starting value `[]`.
- Sets `self.batch_limit` to `3`.
- Sets `self.closed` to `False`.

**Lines 146 to 148**

```python
    def get_queue_receiver(self, queue, **kwargs):
        self.receivers.append({"queue": queue, **kwargs})
        return _SdkReceiverStub()
```

**Method `get_queue_receiver`** takes `queue`, `**kwargs` (all extra named values).

What happens, step by step:

- Calls `self.receivers.append({'queue': queue, **kwargs})`.
- Returns `_SdkReceiverStub()`.

**Lines 150 to 172**

```python
    def get_queue_sender(self, queue):
        client = self

        class Sender:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def create_message_batch(self):
                class Batch(list[Any]):
                    def add_message(self, message):
                        if len(self) >= client.batch_limit:
                            raise ValueError("batch full")
                        self.append(message)

                return Batch()

            def send_messages(self, batch):
                client.sent.append(list(batch))

        return Sender()
```

**Method `get_queue_sender`** takes `queue`.

**New idea.** `__enter__` and `__exit__` are the dunder methods that make an object usable in a `with` block: `__enter__` runs at the start and `__exit__` at the end, even after an error.

What happens, step by step:

- Sets `client` to `self`.
- Defines the class `Sender`.
- Returns `Sender()`.

Names used here:

- `ValueError` is Python's error for a value of the right type but unacceptable content.

**Lines 174 to 175**

```python
    def close(self):
        self.closed = True
```

**Method `close`** takes no parameters.

What happens, step by step:

- Sets `self.closed` to `True`.

**Lines 178 to 181**

```python
def _messaging():
    messaging = ServiceBusMessaging("mybus.servicebus.windows.net", "orders", _Credential())  # type: ignore[arg-type]
    messaging._client = _ClientStub()  # type: ignore[assignment]
    return messaging, messaging._client
```

**Function `_messaging`** takes no parameters.

What happens, step by step:

- Sets `messaging` to the result of calling `ServiceBusMessaging('mybus.servicebus.windows.net', 'orders', _Credential())`.
- Sets `messaging._client` to the result of calling `_ClientStub()`.
- Returns `(messaging, messaging._client)`.

**Lines 184 to 193**

```python
def test_the_main_inbox_opens_a_peek_lock_receiver_with_renewal():
    messaging, client = _messaging()
    receiver = messaging.inbox(sessions=False, max_wait_seconds=10, lock_renewal_seconds=300).open()
    assert receiver is not None
    options = client.receivers[0]
    assert options["queue"] == "orders"
    assert options["session_id"] is None
    assert options["sub_queue"] is None
    assert options["auto_lock_renewer"] is not None
    receiver.close()
```

**Function `test_the_main_inbox_opens_a_peek_lock_receiver_with_renewal`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Sets `receiver` to the result of calling `messaging.inbox(sessions=False, max_wait_seconds=10, lock_renewal_seconds=300).open()`.
- Checks that `receiver` is not exactly `None`.
- Sets `options` to `client.receivers[0]`.
- Checks that `options['queue']` equals `'orders'`.
- Checks that `options['session_id']` is exactly `None`.
- Checks that `options['sub_queue']` is exactly `None`.
- Checks that `options['auto_lock_renewer']` is not exactly `None`.
- Calls `receiver.close()`.

**Lines 196 to 199**

```python
def test_without_renewal_no_renewer_is_created():
    messaging, client = _messaging()
    messaging.inbox(sessions=False, max_wait_seconds=10, lock_renewal_seconds=0).open()
    assert client.receivers[0]["auto_lock_renewer"] is None
```

**Function `test_without_renewal_no_renewer_is_created`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Calls `messaging.inbox(sessions=False, max_wait_seconds=10, lock_renewal_seconds=0).open()`.
- Checks that `client.receivers[0]['auto_lock_renewer']` is exactly `None`.

**Lines 202 to 205**

```python
def test_a_session_inbox_asks_for_the_next_available_session():
    messaging, client = _messaging()
    messaging.inbox(sessions=True, max_wait_seconds=10, lock_renewal_seconds=0).open()
    assert client.receivers[0]["session_id"] == NEXT_AVAILABLE_SESSION
```

**Function `test_a_session_inbox_asks_for_the_next_available_session`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Calls `messaging.inbox(sessions=True, max_wait_seconds=10, lock_renewal_seconds=0).open()`.
- Checks that `client.receivers[0]['session_id']` equals `NEXT_AVAILABLE_SESSION`.

**Lines 208 to 213**

```python
def test_the_dead_letter_inbox_reads_the_dead_letter_sub_queue_and_never_uses_sessions():
    messaging, client = _messaging()
    messaging.dead_letters(max_wait_seconds=5).open()
    options = client.receivers[0]
    assert options["sub_queue"] == ServiceBusSubQueue.DEAD_LETTER
    assert options["session_id"] is None
```

**Function `test_the_dead_letter_inbox_reads_the_dead_letter_sub_queue_and_never_uses_sessions`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Calls `messaging.dead_letters(max_wait_seconds=5).open()`.
- Sets `options` to `client.receivers[0]`.
- Checks that `options['sub_queue']` equals `ServiceBusSubQueue.DEAD_LETTER`.
- Checks that `options['session_id']` is exactly `None`.

**Lines 216 to 222**

```python
def test_the_sender_starts_a_new_batch_when_one_is_full_and_sends_the_remainder():
    messaging, client = _messaging()
    messages = [OutgoingMessage("{}", f"m-{n}", "c01") for n in range(7)]
    messaging.sender().send(messages)
    assert [len(batch) for batch in client.sent] == [3, 3, 1]
    assert client.sent[0][0].message_id == "m-0"
    assert client.sent[0][0].session_id == "c01"
```

**Function `test_the_sender_starts_a_new_batch_when_one_is_full_and_sends_the_remainder`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Sets `messages` to `[OutgoingMessage('{}', f'm-{n}', 'c01') for n in range(7)]`.
- Calls `messaging.sender().send(messages)`.
- Checks that `[len(batch) for batch in client.sent]` equals `[3, 3, 1]`.
- Checks that `client.sent[0][0].message_id` equals `'m-0'`.
- Checks that `client.sent[0][0].session_id` equals `'c01'`.

**Lines 225 to 229**

```python
def test_the_context_manager_closes_the_connection():
    messaging, client = _messaging()
    with messaging:
        pass
    assert client.closed
```

**Function `test_the_context_manager_closes_the_connection`** takes no parameters.

What happens, step by step:

- Sets `(messaging, client)` to the result of calling `_messaging()`.
- Inside a block that `messaging`:
  - `pass`: do nothing.
- Checks that `client.closed` is true.

**Lines 232 to 239**

```python
def test_connect_builds_a_client_without_contacting_azure_and_needs_a_namespace():
    settings = Settings.from_env(
        {"SB_NAMESPACE": "mybus.servicebus.windows.net", "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000000"}
    )
    with connect(settings) as messaging:
        assert messaging.inbox(sessions=False, max_wait_seconds=1, lock_renewal_seconds=0) is not None
    with pytest.raises(ConfigError):
        connect(Settings.from_env({}, require_namespace=False))
```

**Function `test_connect_builds_a_client_without_contacting_azure_and_needs_a_namespace`** takes no parameters.

What happens, step by step:

- Sets `settings` to the result of calling `Settings.from_env` with `{'SB_NAMESPACE': 'mybus.servicebus.windows.net', 'AZURE_CLIENT_ID': '00000000-0000-0000-0000-000000000000'}`.
- Inside a block that `connect(settings)` and call it `messaging`:
  - Checks that `messaging.inbox(sessions=False, max_wait_seconds=1, lock_renewal_seconds=0)` is not exactly `None`.
- Inside a block that expects an error: `pytest.raises(ConfigError)`:
  - Calls `connect(Settings.from_env({}, require_namespace=False))`.

#### `tests/unit/infrastructure/test_settings_logging_clock_shutdown.py`

119 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```python
import json
import logging
import signal
import urllib.error
import urllib.request
```

**New idea.** **HTTP** is the protocol of the web. A client sends a *request* (a method such as GET or POST, a path, headers and sometimes a body) and the server sends back a *response* with a three-digit **status code**: 200 means success, 201 created, 400 the request was bad, 403 forbidden, 404 not found, 413 too large, 502 a server behind this one failed.

What happens, step by step:

- `json`: the standard-library module for JSON.
- `logging`: the standard-library module for log records.
- `signal`: the standard-library module for operating-system signals.
- `urllib.error`: the standard-library module of HTTP error classes.
- `urllib.request`: the standard-library module for sending HTTP requests.

**Line 7**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 9 to 14**

```python
from order_worker.domain.processing import Mode
from order_worker.infrastructure.clock import SystemClock
from order_worker.infrastructure.health_server import HealthServer
from order_worker.infrastructure.logging import JsonFormatter, configure_logging
from order_worker.infrastructure.settings import ConfigError, Settings
from order_worker.infrastructure.shutdown import ShutdownFlag
```

**New idea.** A **thread** is a second line of execution inside one program, running at the same time as the main one. Threads share the program's memory, so data they both touch must be protected, for example with a lock.

**New idea.** A **signal** is a short message the operating system sends to a process. `SIGTERM` asks it to stop politely (a program should finish its current work and exit), `SIGINT` is what Ctrl+C sends, and `SIGKILL` cannot be caught. Container platforms send `SIGTERM` when they stop a container.

What happens, step by step:

- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `SystemClock` from the repository's own module `order_worker.infrastructure.clock`: Monotonic time and a real sleep (defined in `src/order_worker/infrastructure/clock.py`)
- `HealthServer` from the repository's own module `order_worker.infrastructure.health_server`: Serves `/live` and `/ready` on a background thread (defined in `src/order_worker/infrastructure/health_server.py`)
- `JsonFormatter` from the repository's own module `order_worker.infrastructure.logging`: Render a record as JSON; fields passed through `extra=` become top-level keys (defined in `src/order_worker/infrastructure/logging.py`)
- `configure_logging` from the repository's own module `order_worker.infrastructure.logging`: Send the root logger to stdout as JSON at `level`; calling it twice does not duplicate lines (defined in `src/order_worker/infrastructure/logging.py`)
- `ConfigError` from the repository's own module `order_worker.infrastructure.settings`: One or more settings are missing or malformed; the message lists all of them (defined in `src/order_worker/infrastructure/settings.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `ShutdownFlag` from the repository's own module `order_worker.infrastructure.shutdown`: A flag set by SIGTERM or SIGINT (defined in `src/order_worker/infrastructure/shutdown.py`)

**Line 16**

```python
NAMESPACE = {"SB_NAMESPACE": "mybus.servicebus.windows.net"}
```

What happens, step by step:

- Sets `NAMESPACE` to `{'SB_NAMESPACE': 'mybus.servicebus.windows.net'}`.

**Lines 19 to 25**

```python
def test_defaults_match_the_lessons_plain_queue_and_idempotent_mode():
    settings = Settings.from_env(NAMESPACE)
    assert (settings.queue, settings.use_sessions, settings.mode) == ("orders", False, Mode.IDEMPOTENT)
    assert settings.lock_renewal_seconds == 0
    assert settings.chaos.slow_every == 0
    assert settings.max_wait_seconds == 10
    assert settings.health_port is None
```

**Function `test_defaults_match_the_lessons_plain_queue_and_idempotent_mode`** takes no parameters.

What happens, step by step:

- Sets `settings` to the result of calling `Settings.from_env(NAMESPACE)`.
- Checks that `(settings.queue, settings.use_sessions, settings.mode)` equals `('orders', False, Mode.IDEMPOTENT)`.
- Checks that `settings.lock_renewal_seconds` equals `0`.
- Checks that `settings.chaos.slow_every` equals `0`.
- Checks that `settings.max_wait_seconds` equals `10`.
- Checks that `settings.health_port` is exactly `None`.

**Lines 28 to 30**

```python
def test_use_sessions_selects_the_session_queue_unless_a_queue_is_named():
    assert Settings.from_env({**NAMESPACE, "USE_SESSIONS": "1"}).queue == "orders-sessions"
    assert Settings.from_env({**NAMESPACE, "USE_SESSIONS": "1", "SB_QUEUE": "mine"}).queue == "mine"
```

**Function `test_use_sessions_selects_the_session_queue_unless_a_queue_is_named`** takes no parameters.

What happens, step by step:

- Checks that `Settings.from_env({**NAMESPACE, 'USE_SESSIONS': '1'}).queue` equals `'orders-sessions'`.
- Checks that `Settings.from_env({**NAMESPACE, 'USE_SESSIONS': '1', 'SB_QUEUE': 'mine'}).queue` equals `'mine'`.

**Lines 33 to 42**

```python
def test_the_lessons_step_2_settings_are_read():
    settings = Settings.from_env(
        {**NAMESPACE, "MODE": "naive", "SLOW_EVERY": "10", "SLOW_SECONDS": "45", "LOCK_RENEWAL_SECONDS": "300"}
    )
    assert (settings.mode, settings.chaos.slow_every, settings.chaos.slow_seconds, settings.lock_renewal_seconds) == (
        Mode.NAIVE,
        10,
        45.0,
        300,
    )
```

**Function `test_the_lessons_step_2_settings_are_read`** takes no parameters.

What happens, step by step:

- Sets `settings` to the result of calling `Settings.from_env` with `{**NAMESPACE, 'MODE': 'naive', 'SLOW_EVERY': '10', 'SLOW_SECONDS': '45', 'LOCK_RENEWAL_SECONDS': '300'}`.
- Checks that `(settings.mode, settings.chaos.slow_every, settings.chaos.slow_seconds, settings.lock_renewal_seconds)` equals `(Mode.NAIVE, 10, 45.0, 300)`.

**Lines 45 to 58**

```python
def test_every_problem_is_reported_at_once():
    with pytest.raises(ConfigError) as caught:
        Settings.from_env(
            {
                "SB_NAMESPACE": "https://x",
                "MODE": "fast",
                "SLOW_EVERY": "-1",
                "LOG_LEVEL": "LOUD",
                "MAX_WAIT_SECONDS": "0",
            }
        )
    message = str(caught.value)
    for name in ("SB_NAMESPACE", "MODE", "SLOW_EVERY", "LOG_LEVEL", "MAX_WAIT_SECONDS"):
        assert name in message
```

**New idea.** **TLS** is the protocol that encrypts a network connection and proves who is on the other end, which is what the `s` in `https` stands for. The server proves its identity with a **certificate**, a signed document that names the server and carries its public key; a client refuses a certificate it cannot trust.

**New idea.** A **URL** is the full address of something on the web, such as `https://example.com:8443/path?x=1`: the protocol, the host name, an optional port, the path and an optional query.

**Function `test_every_problem_is_reported_at_once`** takes no parameters.

What happens, step by step:

- Inside a block that expects an error: `pytest.raises(ConfigError)`:
  - Calls `Settings.from_env` with `{'SB_NAMESPACE': 'https://x', 'MODE': 'fast', 'SLOW_EVERY': '-1', 'LOG_LEVEL': 'LOUD', 'MAX_WAIT_SECONDS': '0…` (long; see the quote).
- Sets `message` to the result of calling `str(caught.value)`.
- For each `name` in `('SB_NAMESPACE', 'MODE', 'SLOW_EVERY', 'LOG_LEVEL', 'MAX_WAIT_SECONDS')`:
  - Checks that `name` is one of / is inside `message`.

**Lines 61 to 62**

```python
def test_the_namespace_is_optional_for_the_offline_programs():
    assert Settings.from_env({}, require_namespace=False).namespace is None
```

**Function `test_the_namespace_is_optional_for_the_offline_programs`** takes no parameters.

What happens, step by step:

- Checks that `Settings.from_env({}, require_namespace=False).namespace` is exactly `None`.

**Lines 65 to 69**

```python
def test_a_json_log_line_carries_the_message_and_the_extra_fields():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "out of order: %s", ("c01",), None)
    record.customer_id = "c01"
    payload = json.loads(JsonFormatter().format(record))
    assert (payload["msg"], payload["customer_id"], payload["level"]) == ("out of order: c01", "c01", "ERROR")
```

**Function `test_a_json_log_line_carries_the_message_and_the_extra_fields`** takes no parameters.

What happens, step by step:

- Sets `record` to the result of calling `logging.LogRecord('x', logging.ERROR, __file__, 1, 'out of order: %s', ('c01',), None)`.
- Sets `record.customer_id` to `'c01'`.
- Sets `payload` to the result of calling `json.loads(JsonFormatter().format(record))`.
- Checks that `(payload['msg'], payload['customer_id'], payload['level'])` equals `('out of order: c01', 'c01', 'ERROR')`.

Names used here:

- A `LogRecord` holds everything about one log call: level, message, time, extra fields.
- `format` is the repository's own: Return the JSON line for `record` (defined in `src/order_worker/infrastructure/logging.py`)

**Lines 72 to 79**

```python
def test_an_exception_is_included_in_the_json_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc"]
```

**Function `test_an_exception_is_included_in_the_json_line`** takes no parameters.

What happens, step by step:

- Try:
  - Raises `ValueError('boom')`.
- If `ValueError` is raised:
  - Imports `sys`.
  - Sets `record` to the result of calling `logging.LogRecord('x', logging.ERROR, __file__, 1, 'failed', (), sys.exc_info())`.
- Checks that `'ValueError: boom'` is one of / is inside `json.loads(JsonFormatter().format(record))['exc']`.

**Lines 82 to 86**

```python
def test_configuring_logging_twice_leaves_one_handler():
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(logging.getLogger().handlers) == 1
    configure_logging("INFO")
```

**Function `test_configuring_logging_twice_leaves_one_handler`** takes no parameters.

**New idea.** `logging.getLogger("name")` returns the logger with that name. Code writes records with `.info`, `.warning`, `.error`; handlers decide where the records go and in what format.

What happens, step by step:

- Calls `configure_logging('INFO')`.
- Calls `configure_logging('DEBUG')`.
- Checks that `len(logging.getLogger().handlers)` equals `1`.
- Calls `configure_logging('INFO')`.

Names used here:

- `logging.getLogger(name)` returns the named logger.

**Lines 89 to 93**

```python
def test_the_real_clock_moves_forward_and_sleeps():
    clock = SystemClock()
    before = clock.now()
    clock.sleep(0.01)
    assert clock.now() - before >= 0.01
```

**Function `test_the_real_clock_moves_forward_and_sleeps`** takes no parameters.

What happens, step by step:

- Sets `clock` to the result of calling `SystemClock()`.
- Sets `before` to the result of calling `clock.now()`.
- Calls `clock.sleep(0.01)`.
- Checks that `clock.now() - before` is at least `0.01`.

**Lines 96 to 103**

```python
def test_a_stop_request_sets_the_flag_and_a_second_signal_exits_at_once():
    flag = ShutdownFlag()
    assert not flag.is_set()
    flag._handle(signal.SIGTERM, None)
    assert flag.is_set()
    with pytest.raises(SystemExit) as caught:
        flag._handle(signal.SIGTERM, None)
    assert caught.value.code == 128 + signal.SIGTERM
```

**Function `test_a_stop_request_sets_the_flag_and_a_second_signal_exits_at_once`** takes no parameters.

What happens, step by step:

- Sets `flag` to the result of calling `ShutdownFlag()`.
- Checks that it is not the case that `flag.is_set()` is true.
- Calls `flag._handle(signal.SIGTERM, None)`.
- Checks that `flag.is_set()` is true.
- Inside a block that expects an error: `pytest.raises(SystemExit)`:
  - Calls `flag._handle(signal.SIGTERM, None)`.
- Checks that `caught.value.code` equals `128 + signal.SIGTERM`.

Names used here:

- `is_set` is the repository's own: True once a stop was requested (defined in `src/order_worker/infrastructure/shutdown.py`)
- `_handle` is the repository's own: no description in the code (defined in `src/order_worker/infrastructure/shutdown.py`)

**Lines 106 to 115**

```python
def test_installing_the_handlers_routes_the_signals_to_the_flag():
    previous = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    flag = ShutdownFlag()
    try:
        flag.install()
        signal.raise_signal(signal.SIGTERM)
        assert flag.is_set()
    finally:
        signal.signal(signal.SIGTERM, previous[0])
        signal.signal(signal.SIGINT, previous[1])
```

**Function `test_installing_the_handlers_routes_the_signals_to_the_flag`** takes no parameters.

What happens, step by step:

- Sets `previous` to `(signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))`.
- Sets `flag` to the result of calling `ShutdownFlag()`.
- Try:
  - Calls `flag.install()`.
  - Calls `signal.raise_signal(signal.SIGTERM)`.
  - Checks that `flag.is_set()` is true.
- Always, in the end:
  - Calls `signal.signal(signal.SIGTERM, previous[0])`.
  - Calls `signal.signal(signal.SIGINT, previous[1])`.

Names used here:

- `install` is the repository's own: Route SIGTERM and SIGINT to this flag (defined in `src/order_worker/infrastructure/shutdown.py`)
- `signal.signal(SIGTERM, handler)` registers a function to run when the operating system asks the program to stop.

**Lines 118 to 123**

```python
def _get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
```

**New idea.** An **IP address** such as `10.10.2.4` identifies a computer on a network. A **CIDR range** such as `10.10.2.0/24` names a block of addresses: the number after the slash says how many leading bits are fixed, so `/24` fixes the first three numbers and leaves 256 addresses. Ranges starting `10.`, `172.16.` to `172.31.` and `192.168.` are *private*: they are not reachable from the public internet.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

**Function `_get`** takes `port`, `path`.

What happens, step by step:

- Try:
  - Inside a block that `urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5)` and call it `response`:
    - Returns `response.status`.
- If `urllib.error.HTTPError` is raised (the error is called `error`):
  - Returns `error.code`.

Names used here:

- `urllib.request.urlopen(request)` sends an HTTP request using only the standard library.

**Lines 126 to 137**

```python
def test_live_is_ok_while_the_loop_beats_and_fails_when_it_goes_quiet():
    now = {"t": 100.0}
    server = HealthServer(0, stale_after_seconds=30, ledger_ok=lambda: True, monotonic=lambda: now["t"])
    server.start()
    try:
        assert _get(server.port, "/live") == 200
        now["t"] += 31
        assert _get(server.port, "/live") == 503
        server.beat()
        assert _get(server.port, "/live") == 200
    finally:
        server.stop()
```

**Function `test_live_is_ok_while_the_loop_beats_and_fails_when_it_goes_quiet`** takes no parameters.

What happens, step by step:

- Sets `now` to `{'t': 100.0}`.
- Sets `server` to the result of calling `HealthServer(0, stale_after_seconds=30, ledger_ok=lambda: True, monotonic=lambda: now['t'])`.
- Calls `server.start()`.
- Try:
  - Checks that `_get(server.port, '/live')` equals `200`.
  - Updates `now['t']` with `=` `31`.
  - Checks that `_get(server.port, '/live')` equals `503`.
  - Calls `server.beat()`.
  - Checks that `_get(server.port, '/live')` equals `200`.
- Always, in the end:
  - Calls `server.stop()`.

Names used here:

- `start` is the repository's own: Start serving (defined in `src/order_worker/infrastructure/health_server.py`)
- `beat` is the repository's own: Record that the receive loop is making progress (defined in `src/order_worker/infrastructure/health_server.py`)
- `stop` is the repository's own: Stop serving and release the port (defined in `src/order_worker/infrastructure/health_server.py`)

**Lines 140 to 151**

```python
def test_ready_also_needs_the_ledger_and_unknown_paths_are_404():
    healthy = {"ledger": True}
    server = HealthServer(0, stale_after_seconds=60, ledger_ok=lambda: healthy["ledger"])
    server.start()
    try:
        assert _get(server.port, "/ready") == 200
        healthy["ledger"] = False
        assert _get(server.port, "/ready") == 503
        assert _get(server.port, "/live") == 200
        assert _get(server.port, "/nope") == 404
    finally:
        server.stop()
```

**Function `test_ready_also_needs_the_ledger_and_unknown_paths_are_404`** takes no parameters.

What happens, step by step:

- Sets `healthy` to `{'ledger': True}`.
- Sets `server` to the result of calling `HealthServer(0, stale_after_seconds=60, ledger_ok=lambda: healthy['ledger'])`.
- Calls `server.start()`.
- Try:
  - Checks that `_get(server.port, '/ready')` equals `200`.
  - Sets `healthy['ledger']` to `False`.
  - Checks that `_get(server.port, '/ready')` equals `503`.
  - Checks that `_get(server.port, '/live')` equals `200`.
  - Checks that `_get(server.port, '/nope')` equals `404`.
- Always, in the end:
  - Calls `server.stop()`.

#### `tests/unit/infrastructure/test_simulation.py`

129 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The simulated broker must behave like Service Bus where the lesson depends on it."""
```

The module docstring says: The simulated broker must behave like Service Bus where the lesson depends on it.

**Line 3**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 5 to 7**

```python
from order_worker.application.ports import OutgoingMessage
from order_worker.domain.errors import LockLostError
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker
```

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)
- `ManualClock` from the repository's own module `order_worker.infrastructure.simulation`: Time that moves only when someone sleeps (defined in `src/order_worker/infrastructure/simulation.py`)
- `SimulatedBroker` from the repository's own module `order_worker.infrastructure.simulation`: One queue and its dead-letter sub-queue (defined in `src/order_worker/infrastructure/simulation.py`)

**Lines 10 to 13**

```python
def _broker(**kwargs):
    clock = ManualClock()
    broker = SimulatedBroker(clock, **kwargs)
    return clock, broker
```

**Function `_broker`** takes `**kwargs` (all extra named values).

What happens, step by step:

- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock, **kwargs)`.
- Returns `(clock, broker)`.

**Lines 16 to 17**

```python
def _send(broker, *ids, session=None):
    broker.send([OutgoingMessage("{}", message_id, session) for message_id in ids])
```

**Function `_send`** takes `broker`, `*ids` (all extra positional values), `session` (by name only), default `None`.

What happens, step by step:

- Calls `broker.send([OutgoingMessage('{}', message_id, session) for message_id in ids])`.

**Lines 20 to 27**

```python
def test_a_received_message_is_hidden_from_other_receivers_while_locked():
    _, broker = _broker()
    _send(broker, "a")
    first = broker.inbox().open().receive(1)
    assert first is not None
    assert first.delivery_count == 1
    assert broker.inbox().open().receive(1) is None
    assert broker.counts().locked == 1
```

**Function `test_a_received_message_is_hidden_from_other_receivers_while_locked`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'a')`.
- Sets `first` to the result of calling `broker.inbox().open().receive(1)`.
- Checks that `first` is not exactly `None`.
- Checks that `first.delivery_count` equals `1`.
- Checks that `broker.inbox().open().receive(1)` is exactly `None`.
- Checks that `broker.counts().locked` equals `1`.

Names used here:

- `counts` is the repository's own: How many messages are active, locked and dead-lettered right now (defined in `src/order_worker/infrastructure/simulation.py`)

**Lines 30 to 34**

```python
def test_complete_inside_the_lock_removes_the_message():
    _, broker = _broker()
    _send(broker, "a")
    broker.inbox().open().receive(1).complete()
    assert (broker.counts().active, broker.counts().locked) == (0, 0)
```

**Function `test_complete_inside_the_lock_removes_the_message`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'a')`.
- Calls `broker.inbox().open().receive(1).complete()`.
- Checks that `(broker.counts().active, broker.counts().locked)` equals `(0, 0)`.

**Lines 37 to 47**

```python
def test_a_message_whose_lock_expires_is_delivered_again_with_a_higher_count_and_the_late_complete_fails():
    clock, broker = _broker()
    _send(broker, "a")
    receiver = broker.inbox().open()
    late = receiver.receive(1)
    clock.sleep(31)  # past the 30 s lock
    again = receiver.receive(1)
    assert again is not None
    assert again.delivery_count == 2
    with pytest.raises(LockLostError, match="lock supplied is invalid"):
        late.complete()
```

**Function `test_a_message_whose_lock_expires_is_delivered_again_with_a_higher_count_and_the_late_complete_fails`** takes no parameters.

What happens, step by step:

- Sets `(clock, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'a')`.
- Sets `receiver` to the result of calling `broker.inbox().open()`.
- Sets `late` to the result of calling `receiver.receive(1)`.
- Calls `clock.sleep(31)`.
- Sets `again` to the result of calling `receiver.receive(1)`.
- Checks that `again` is not exactly `None`.
- Checks that `again.delivery_count` equals `2`.
- Inside a block that expects an error: `pytest.raises(LockLostError, match='lock supplied is invalid')`:
  - Calls `late.complete()`.

**Lines 50 to 56**

```python
def test_complete_after_expiry_fails_even_when_nobody_took_the_message_again():
    clock, broker = _broker()
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(31)
    with pytest.raises(LockLostError):
        delivery.complete()
```

**Function `test_complete_after_expiry_fails_even_when_nobody_took_the_message_again`** takes no parameters.

What happens, step by step:

- Sets `(clock, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'a')`.
- Sets `delivery` to the result of calling `broker.inbox().open().receive(1)`.
- Calls `clock.sleep(31)`.
- Inside a block that expects an error: `pytest.raises(LockLostError)`:
  - Calls `delivery.complete()`.

**Lines 59 to 65**

```python
def test_auto_renewal_keeps_the_lock_valid_for_slow_work():
    clock, broker = _broker(auto_renew_seconds=300)
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(45)
    delivery.complete()
    assert broker.counts().active == 0
```

**Function `test_auto_renewal_keeps_the_lock_valid_for_slow_work`** takes no parameters.

What happens, step by step:

- Sets `(clock, broker)` to the result of calling `_broker(auto_renew_seconds=300)`.
- Calls `_send(broker, 'a')`.
- Sets `delivery` to the result of calling `broker.inbox().open().receive(1)`.
- Calls `clock.sleep(45)`.
- Calls `delivery.complete()`.
- Checks that `broker.counts().active` equals `0`.

**Lines 68 to 74**

```python
def test_auto_renewal_ends_after_its_maximum():
    clock, broker = _broker(auto_renew_seconds=60)
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(61)
    with pytest.raises(LockLostError):
        delivery.complete()
```

**Function `test_auto_renewal_ends_after_its_maximum`** takes no parameters.

What happens, step by step:

- Sets `(clock, broker)` to the result of calling `_broker(auto_renew_seconds=60)`.
- Calls `_send(broker, 'a')`.
- Sets `delivery` to the result of calling `broker.inbox().open().receive(1)`.
- Calls `clock.sleep(61)`.
- Inside a block that expects an error: `pytest.raises(LockLostError)`:
  - Calls `delivery.complete()`.

**Lines 77 to 82**

```python
def test_abandon_makes_the_message_available_at_once():
    _, broker = _broker()
    _send(broker, "a")
    receiver = broker.inbox().open()
    receiver.receive(1).abandon()
    assert receiver.receive(1).delivery_count == 2
```

**Function `test_abandon_makes_the_message_available_at_once`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'a')`.
- Sets `receiver` to the result of calling `broker.inbox().open()`.
- Calls `receiver.receive(1).abandon()`.
- Checks that `receiver.receive(1).delivery_count` equals `2`.

**Lines 85 to 93**

```python
def test_a_message_delivered_the_maximum_number_of_times_goes_to_the_dead_letter_queue():
    _, broker = _broker(max_delivery_count=3)
    _send(broker, "a")
    receiver = broker.inbox().open()
    for _ in range(3):
        receiver.receive(1).abandon()
    assert receiver.receive(1) is None
    assert broker.dead_letter_reasons()[0][:2] == ("a", "MaxDeliveryCountExceeded")
    assert broker.max_delivery_seen() == 3
```

**Function `test_a_message_delivered_the_maximum_number_of_times_goes_to_the_dead_letter_queue`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker(max_delivery_count=3)`.
- Calls `_send(broker, 'a')`.
- Sets `receiver` to the result of calling `broker.inbox().open()`.
- For each `_` in `range(3)`:
  - Calls `receiver.receive(1).abandon()`.
- Checks that `receiver.receive(1)` is exactly `None`.
- Checks that `broker.dead_letter_reasons()[0][:2]` equals `('a', 'MaxDeliveryCountExceeded')`.
- Checks that `broker.max_delivery_seen()` equals `3`.

Names used here:

- `max_delivery_seen` is the repository's own: The highest delivery count any message ever reached, including messages already completed (defined in `src/order_worker/infrastructure/simulation.py`)

**Lines 96 to 102**

```python
def test_explicit_dead_lettering_records_reason_and_description_and_other_messages_keep_flowing():
    _, broker = _broker()
    _send(broker, "bad", "good")
    receiver = broker.inbox().open()
    receiver.receive(1).dead_letter("InvalidAmount", "amount is not a number")
    assert receiver.receive(1).message_id == "good"
    assert broker.dead_letter_reasons() == [("bad", "InvalidAmount", "amount is not a number")]
```

**Function `test_explicit_dead_lettering_records_reason_and_description_and_other_messages_keep_flowing`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'bad', 'good')`.
- Sets `receiver` to the result of calling `broker.inbox().open()`.
- Calls `receiver.receive(1).dead_letter('InvalidAmount', 'amount is not a number')`.
- Checks that `receiver.receive(1).message_id` equals `'good'`.
- Checks that `broker.dead_letter_reasons()` equals `[('bad', 'InvalidAmount', 'amount is not a number')]`.

**Lines 105 to 122**

```python
def test_a_dead_letter_receiver_reads_reason_and_description_and_can_remove_or_release_messages():
    _, broker = _broker()
    _send(broker, "bad")
    broker.inbox().open().receive(1).dead_letter("InvalidAmount", "amount is not a number")
    receiver = broker.dead_letters().open()
    dead = receiver.receive(1)
    assert (dead.dead_letter_reason, dead.dead_letter_description, dead.delivery_count) == (
        "InvalidAmount",
        "amount is not a number",
        1,
    )
    dead.abandon()
    again = receiver.receive(1)
    assert again is not None
    again.complete()
    assert receiver.receive(1) is None
    receiver.close()
    assert broker.counts().dead == 0
```

**Function `test_a_dead_letter_receiver_reads_reason_and_description_and_can_remove_or_release_messages`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'bad')`.
- Calls `broker.inbox().open().receive(1).dead_letter('InvalidAmount', 'amount is not a number')`.
- Sets `receiver` to the result of calling `broker.dead_letters().open()`.
- Sets `dead` to the result of calling `receiver.receive(1)`.
- Checks that `(dead.dead_letter_reason, dead.dead_letter_description, dead.delivery_count)` equals `('InvalidAmount', 'amount is not a number', 1)`.
- Calls `dead.abandon()`.
- Sets `again` to the result of calling `receiver.receive(1)`.
- Checks that `again` is not exactly `None`.
- Calls `again.complete()`.
- Checks that `receiver.receive(1)` is exactly `None`.
- Calls `receiver.close()`.
- Checks that `broker.counts().dead` equals `0`.

**Lines 125 to 131**

```python
def test_a_dead_letter_cannot_be_dead_lettered_again():
    _, broker = _broker()
    _send(broker, "bad")
    broker.inbox().open().receive(1).dead_letter("x", "y")
    dead = broker.dead_letters().open().receive(1)
    with pytest.raises(NotImplementedError):
        dead.dead_letter("a", "b")
```

**Function `test_a_dead_letter_cannot_be_dead_lettered_again`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker()`.
- Calls `_send(broker, 'bad')`.
- Calls `broker.inbox().open().receive(1).dead_letter('x', 'y')`.
- Sets `dead` to the result of calling `broker.dead_letters().open().receive(1)`.
- Inside a block that expects an error: `pytest.raises(NotImplementedError)`:
  - Calls `dead.dead_letter('a', 'b')`.

**Lines 134 to 137**

```python
def test_an_empty_receive_waits_so_virtual_time_passes():
    clock, broker = _broker()
    assert broker.inbox().open().receive(10) is None
    assert clock.now() == 10
```

**Function `test_an_empty_receive_waits_so_virtual_time_passes`** takes no parameters.

What happens, step by step:

- Sets `(clock, broker)` to the result of calling `_broker()`.
- Checks that `broker.inbox().open().receive(10)` is exactly `None`.
- Checks that `clock.now()` equals `10`.

**Lines 140 to 143**

```python
def test_a_session_queue_refuses_a_message_without_a_session_id():
    _, broker = _broker(sessions=True)
    with pytest.raises(ValueError, match="session"):
        _send(broker, "a")
```

**Function `test_a_session_queue_refuses_a_message_without_a_session_id`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker(sessions=True)`.
- Inside a block that expects an error: `pytest.raises(ValueError, match='session')`:
  - Calls `_send(broker, 'a')`.

**Lines 146 to 155**

```python
def test_one_receiver_holds_a_session_and_gets_its_messages_in_order_while_others_get_other_sessions():
    _, broker = _broker(sessions=True)
    _send(broker, "a1", session="c01")
    _send(broker, "b1", session="c02")
    _send(broker, "a2", session="c01")
    inbox = broker.inbox()
    first, second = inbox.open(), inbox.open()
    assert [first.receive(1).message_id, first.receive(1).message_id] == ["a1", "a2"]
    assert second.receive(1).message_id == "b1"
    assert inbox.open() is None  # every session is held
```

**Function `test_one_receiver_holds_a_session_and_gets_its_messages_in_order_while_others_get_other_sessions`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker(sessions=True)`.
- Calls `_send(broker, 'a1', session='c01')`.
- Calls `_send(broker, 'b1', session='c02')`.
- Calls `_send(broker, 'a2', session='c01')`.
- Sets `inbox` to the result of calling `broker.inbox()`.
- Sets `(first, second)` to `(inbox.open(), inbox.open())`.
- Checks that `[first.receive(1).message_id, first.receive(1).message_id]` equals `['a1', 'a2']`.
- Checks that `second.receive(1).message_id` equals `'b1'`.
- Checks that `inbox.open()` is exactly `None`.

**Lines 158 to 165**

```python
def test_closing_a_session_receiver_releases_the_session():
    _, broker = _broker(sessions=True)
    _send(broker, "a1", session="c01")
    inbox = broker.inbox()
    first = inbox.open()
    assert inbox.open() is None
    first.close()
    assert inbox.open() is not None
```

**Function `test_closing_a_session_receiver_releases_the_session`** takes no parameters.

What happens, step by step:

- Sets `(_, broker)` to the result of calling `_broker(sessions=True)`.
- Calls `_send(broker, 'a1', session='c01')`.
- Sets `inbox` to the result of calling `broker.inbox()`.
- Sets `first` to the result of calling `inbox.open()`.
- Checks that `inbox.open()` is exactly `None`.
- Calls `first.close()`.
- Checks that `inbox.open()` is not exactly `None`.

#### `tests/unit/interfaces/test_clis.py`

106 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The command-line programs, run in-process against a simulated broker through a patched `connect`."""
```

The module docstring says: The command-line programs, run in-process against a simulated broker through a patched `connect`.

**Line 3**

```python
import json
```

What happens, step by step:

- `json`: the standard-library module for JSON.

**Line 5**

```python
import pytest
```

What happens, step by step:

- `pytest`: the test framework.

**Lines 7 to 12**

```python
from order_worker.application.ports import OutgoingMessage
from order_worker.domain.commands import POISON_BODY
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database
from order_worker.interfaces import check_cli, dlq_cli, produce_cli, simulate_cli, worker_cli
from order_worker.interfaces.common import parse_cents, run_program
```

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `POISON_BODY` from the repository's own module `order_worker.domain.commands`.
- `ManualClock` from the repository's own module `order_worker.infrastructure.simulation`: Time that moves only when someone sleeps (defined in `src/order_worker/infrastructure/simulation.py`)
- `SimulatedBroker` from the repository's own module `order_worker.infrastructure.simulation`: One queue and its dead-letter sub-queue (defined in `src/order_worker/infrastructure/simulation.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `prepare_database` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql` (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `check_cli` from the repository's own module `order_worker.interfaces`.
- `dlq_cli` from the repository's own module `order_worker.interfaces`.
- `produce_cli` from the repository's own module `order_worker.interfaces`.
- `simulate_cli` from the repository's own module `order_worker.interfaces`.
- `worker_cli` from the repository's own module `order_worker.interfaces`.
- `parse_cents` from the repository's own module `order_worker.interfaces.common`: Turn '10000.0' (currency units) into cents (defined in `src/order_worker/interfaces/common.py`)
- `run_program` from the repository's own module `order_worker.interfaces.common`: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2 (defined in `src/order_worker/interfaces/common.py`)

**Lines 15 to 16**

```python
class _Messaging:
    """Looks like ServiceBusMessaging but is backed by a simulated broker."""
```

The docstring in the code says: Looks like ServiceBusMessaging but is backed by a simulated broker.

**Class `_Messaging`**.

**Lines 18 to 19**

```python
    def __init__(self, broker: SimulatedBroker) -> None:
        self.broker = broker
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`); gives back `None`.

What happens, step by step:

- Sets `self.broker` to `broker`.

**Lines 21 to 22**

```python
    def __enter__(self):
        return self
```

**Method `__enter__`** takes no parameters.

What happens, step by step:

- Returns `self`.

**Lines 24 to 25**

```python
    def __exit__(self, *exc):
        return None
```

**Method `__exit__`** takes `*exc` (all extra positional values).

What happens, step by step:

- Returns `None`.

**Lines 27 to 28**

```python
    def inbox(self, **_kwargs):
        return self.broker.inbox()
```

**Method `inbox`** takes `**_kwargs` (all extra named values).

What happens, step by step:

- Returns `self.broker.inbox()`.

**Lines 30 to 31**

```python
    def dead_letters(self, **_kwargs):
        return self.broker.dead_letters()
```

**Method `dead_letters`** takes `**_kwargs` (all extra named values).

What happens, step by step:

- Returns `self.broker.dead_letters()`.

**Lines 33 to 34**

```python
    def sender(self):
        return self.broker
```

**Method `sender`** takes no parameters.

What happens, step by step:

- Returns `self.broker`.

**Lines 37 to 39**

```python
@pytest.fixture
def broker():
    return SimulatedBroker(ManualClock())
```

**Function `broker`** takes no parameters.

What happens, step by step:

- Decorator `@pytest.fixture`.
- Returns `SimulatedBroker(ManualClock())`.

**Lines 42 to 54**

```python
@pytest.fixture
def env(monkeypatch, database, sql_dir, broker):
    for name, value in {
        "SB_NAMESPACE": "mybus.servicebus.windows.net",
        "LEDGER_PATH": str(database),
        "SQL_DIR": str(sql_dir),
        "MAX_WAIT_SECONDS": "1",
    }.items():
        monkeypatch.setenv(name, value)
    messaging = _Messaging(broker)
    for module in (produce_cli, worker_cli, dlq_cli):
        monkeypatch.setattr(module, "connect", lambda _settings: messaging)
    return broker
```

**Function `env`** takes `monkeypatch`, `database`, `sql_dir`, `broker`.

What happens, step by step:

- Decorator `@pytest.fixture`.
- For each `(name, value)` in `{'SB_NAMESPACE': 'mybus.servicebus.windows.net', 'LEDGER_PATH': str(database), 'SQL_DIR': str(sql_dir), 'MAX_…` (long; see the quote):
  - Calls `monkeypatch.setenv(name, value)`.
- Sets `messaging` to the result of calling `_Messaging(broker)`.
- For each `module` in `(produce_cli, worker_cli, dlq_cli)`:
  - Calls `monkeypatch.setattr(module, 'connect', lambda _settings: messaging)`.
- Returns `broker`.

Names used here:

- `.items()` on a dictionary lists its `(key, value)` pairs.
- `monkeypatch.setenv("NAME", "value")` sets an environment variable for one test.

**Lines 57 to 58**

```python
def test_parse_cents_reads_currency_units():
    assert (parse_cents("10000.0"), parse_cents("10.5"), parse_cents("7")) == (1_000_000, 1050, 700)
```

**Function `test_parse_cents_reads_currency_units`** takes no parameters.

What happens, step by step:

- Checks that `(parse_cents('10000.0'), parse_cents('10.5'), parse_cents('7'))` equals `(1000000, 1050, 700)`.

**Lines 61 to 64**

```python
def test_a_bad_configuration_exits_2_and_names_the_variable(monkeypatch, capsys):
    monkeypatch.setenv("SB_NAMESPACE", "")
    assert run_program(lambda _settings: 0) == 2
    assert "SB_NAMESPACE" in capsys.readouterr().err
```

**Function `test_a_bad_configuration_exits_2_and_names_the_variable`** takes `monkeypatch`, `capsys`.

**New idea.** `capsys` is a built-in pytest fixture that captures what the code prints to standard output and standard error, so a test can read it with `capsys.readouterr()`.

What happens, step by step:

- Calls `monkeypatch.setenv('SB_NAMESPACE', '')`.
- Checks that `run_program(lambda _settings: 0)` equals `2`.
- Checks that `'SB_NAMESPACE'` is one of / is inside `capsys.readouterr().err`.

Names used here:

- `capsys.readouterr()` returns what was printed so far, as `.out` and `.err`.

**Lines 67 to 70**

```python
def test_produce_sends_the_known_set_and_reports_the_count(env, capsys):
    assert produce_cli.main(["--customers", "2", "--per-customer", "3"]) == 0
    assert "sent 7 messages to orders (the last one is the poison command)" in capsys.readouterr().out
    assert env.counts().active == 7
```

**Function `test_produce_sends_the_known_set_and_reports_the_count`** takes `env`, `capsys`.

What happens, step by step:

- Checks that `produce_cli.main(['--customers', '2', '--per-customer', '3'])` equals `0`.
- Checks that `'sent 7 messages to orders (the last one is the poison command)'` is one of / is inside `capsys.readouterr().out`.
- Checks that `env.counts().active` equals `7`.

**Lines 73 to 75**

```python
def test_produce_can_skip_the_poison_command(env, capsys):
    produce_cli.main(["--customers", "1", "--per-customer", "2", "--no-poison"])
    assert "sent 2 messages to orders\n" in capsys.readouterr().out
```

**Function `test_produce_can_skip_the_poison_command`** takes `env`, `capsys`.

What happens, step by step:

- Calls `produce_cli.main(['--customers', '1', '--per-customer', '2', '--no-poison'])`.
- Checks that `'sent 2 messages to orders\n'` is one of / is inside `capsys.readouterr().out`.

**Lines 78 to 86**

```python
def test_the_worker_applies_dead_letters_and_reports_its_counters(env, capsys, monkeypatch):
    produce_cli.main(["--customers", "2", "--per-customer", "3"])
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert worker_cli.main(["--until-idle", "2"]) == 0
    out = capsys.readouterr().out
    assert "applied=6" in out
    assert "dead_lettered=1" in out
    assert "lock_lost=0" in out
    assert env.dead_letter_reasons()[0][:2] == ("o-bad", "InvalidAmount")
```

**Function `test_the_worker_applies_dead_letters_and_reports_its_counters`** takes `env`, `capsys`, `monkeypatch`.

What happens, step by step:

- Calls `produce_cli.main(['--customers', '2', '--per-customer', '3'])`.
- Calls `monkeypatch.setenv('LOG_LEVEL', 'ERROR')`.
- Checks that `worker_cli.main(['--until-idle', '2'])` equals `0`.
- Sets `out` to `capsys.readouterr().out`.
- Checks that `'applied=6'` is one of / is inside `out`.
- Checks that `'dead_lettered=1'` is one of / is inside `out`.
- Checks that `'lock_lost=0'` is one of / is inside `out`.
- Checks that `env.dead_letter_reasons()[0][:2]` equals `('o-bad', 'InvalidAmount')`.

**Lines 89 to 91**

```python
def test_the_worker_serves_a_health_endpoint_when_a_port_is_set(env, monkeypatch, capsys):
    monkeypatch.setenv("HEALTH_PORT", "0")
    assert worker_cli.main(["--until-idle", "1"]) == 0
```

**Function `test_the_worker_serves_a_health_endpoint_when_a_port_is_set`** takes `env`, `monkeypatch`, `capsys`.

What happens, step by step:

- Calls `monkeypatch.setenv('HEALTH_PORT', '0')`.
- Checks that `worker_cli.main(['--until-idle', '1'])` equals `0`.

**Lines 94 to 99**

```python
def test_the_replay_tool_applies_one_action_to_every_dead_letter_for_scripts(env, capsys):
    env.send([OutgoingMessage(POISON_BODY, "o-bad")])
    env.inbox().open().receive(1).dead_letter("InvalidAmount", "amount is not a number")
    assert dlq_cli.main(["--action", "fix"]) == 0
    assert "fixed=1 dropped=0 kept=0" in capsys.readouterr().out
    assert json.loads(env.inbox().open().receive(1).body)["amount"] == 10.0
```

**Function `test_the_replay_tool_applies_one_action_to_every_dead_letter_for_scripts`** takes `env`, `capsys`.

What happens, step by step:

- Calls `env.send([OutgoingMessage(POISON_BODY, 'o-bad')])`.
- Calls `env.inbox().open().receive(1).dead_letter('InvalidAmount', 'amount is not a number')`.
- Checks that `dlq_cli.main(['--action', 'fix'])` equals `0`.
- Checks that `'fixed=1 dropped=0 kept=0'` is one of / is inside `capsys.readouterr().out`.
- Checks that `json.loads(env.inbox().open().receive(1).body)['amount']` equals `10.0`.

**Lines 102 to 110**

```python
def test_the_replay_tool_asks_the_operator_and_repeats_the_question_on_a_bad_answer(env, monkeypatch, capsys):
    env.send([OutgoingMessage(POISON_BODY, "o-bad")])
    env.inbox().open().receive(1).dead_letter("InvalidAmount", "amount is not a number")
    answers = iter(["maybe", "d"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert dlq_cli.main([]) == 0
    out = capsys.readouterr().out
    assert 'o-bad  reason=InvalidAmount  description="amount is not a number"  delivery_count=1' in out
    assert "fixed=0 dropped=1 kept=0" in out
```

**Function `test_the_replay_tool_asks_the_operator_and_repeats_the_question_on_a_bad_answer`** takes `env`, `monkeypatch`, `capsys`.

What happens, step by step:

- Calls `env.send([OutgoingMessage(POISON_BODY, 'o-bad')])`.
- Calls `env.inbox().open().receive(1).dead_letter('InvalidAmount', 'amount is not a number')`.
- Sets `answers` to the result of calling `iter(['maybe', 'd'])`.
- Calls `monkeypatch.setattr('builtins.input', lambda _prompt: next(answers))`.
- Checks that `dlq_cli.main([])` equals `0`.
- Sets `out` to `capsys.readouterr().out`.
- Checks that `'o-bad reason=InvalidAmount description="amount is not a number" delivery_count=1'` is one of / is inside `out`.
- Checks that `'fixed=0 dropped=1 kept=0'` is one of / is inside `out`.

Names used here:

- `next(it, default)` takes the next item from an iterator, or the default if it is used up.

**Lines 113 to 126**

```python
def test_check_exits_0_on_the_exact_end_state_and_1_with_the_mismatch_named(
    env, database, sql_dir, capsys, monkeypatch
):
    prepare_database(database, sql_dir, with_migrations=True)
    ledger = SqliteLedger(database)
    from order_worker.domain.commands import known_commands

    for command in known_commands(2, 3):
        ledger.apply(command.order_id, command, 1, deduplicate=True)
    ledger.close()
    assert check_cli.main(["--expected-rows", "6", "--expected-total", "60.0", "--per-customer", "3"]) == 0
    assert "OK: the ledger is exactly the expected end state" in capsys.readouterr().out
    assert check_cli.main(["--expected-rows", "1000", "--per-customer", "3"]) == 1
    assert "MISMATCH: expected 1000 rows, found 6" in capsys.readouterr().err
```

**Function `test_check_exits_0_on_the_exact_end_state_and_1_with_the_mismatch_named`** takes `env`, `database`, `sql_dir`, `capsys`, `monkeypatch`.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Imports `known_commands` from `order_worker.domain.commands`.
- For each `command` in `known_commands(2, 3)`:
  - Calls `ledger.apply(command.order_id, command, 1, deduplicate=True)`.
- Calls `ledger.close()`.
- Checks that `check_cli.main(['--expected-rows', '6', '--expected-total', '60.0', '--per-customer', '3'])` equals `0`.
- Checks that `'OK: the ledger is exactly the expected end state'` is one of / is inside `capsys.readouterr().out`.
- Checks that `check_cli.main(['--expected-rows', '1000', '--per-customer', '3'])` equals `1`.
- Checks that `'MISMATCH: expected 1000 rows, found 6'` is one of / is inside `capsys.readouterr().err`.

**Lines 129 to 142**

```python
@pytest.mark.parametrize(
    ("args", "expect", "code"),
    [
        (["duplicates", "--mode", "naive"], "dirty", 0),
        (["duplicates", "--mode", "naive"], "clean", 1),
        (["duplicates", "--mode", "idempotent", "--renew", "300"], "clean", 0),
        (["ordering", "--sessions"], "clean", 0),
        (["poison"], "clean", 0),
        (["poison"], "dirty", 1),
    ],
)
def test_the_simulation_exits_by_what_was_expected(args, expect, code, capsys):
    assert simulate_cli.main(["--expect", expect, *args]) == code
    assert capsys.readouterr().out
```

**Function `test_the_simulation_exits_by_what_was_expected`** takes `args`, `expect`, `code`, `capsys`.

What happens, step by step:

- Decorator `@pytest.mark.parametrize(('args', 'expect', 'code'), [(['duplicates', '--mode', 'naive'], 'dirty', 0), (['duplicates', '--mode', 'naive'], 'clean', 1), (['duplicates', '--mode', 'idempotent', '--renew', '300'], 'clean', 0), (['ordering', '--sessions'], 'clean', 0), (['poison'], 'clean', 0), (['poison'], 'dirty', 1)])`.
- Checks that `simulate_cli.main(['--expect', expect, *args])` equals `code`.
- Checks that `capsys.readouterr().out` is true.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `Makefile` | 85, 89, 92, 95, 147 | [make.md](make.md) |
| `pyproject.toml` | 20 to 21, 61 | [pyproject-toml.md](pyproject-toml.md) |
| `.dockerignore` | 6 | [docker.md](docker.md) |
| `.gitignore` | 7 | [git.md](git.md) |

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
