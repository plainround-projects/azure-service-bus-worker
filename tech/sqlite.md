# SQLite

*The small database the worker writes results to. Pinned here: SQLite via Python's `sqlite3` module (SQLite 3.37 or newer for STRICT tables).*

## What it is

SQLite is a database that lives in one ordinary file. There is no server to start: the program that wants the data opens the file through a library (Python's standard `sqlite3` module) and runs SQL against it. It is small, reliable, and ideal for a lesson that does not need a separate database server.

## Why this repository uses it

The lesson says any small database will do. SQLite needs no server, which keeps the lesson about messaging. The ledger is a plain file, `data/orders.db`.

## Where it appears

| File | What it does with it |
|---|---|
| `src/order_worker/infrastructure/sqlite_ledger.py` | The adapter: schema setup, the transaction, reads. |
| `sql/` | The DDL, seed, queries, migration and reset scripts. |
| `Makefile` | `make db`, `make migrate`, `make queries`, `make reset-db` use the `sqlite3` shell. |
| `tests/integration/test_sqlite_ledger.py` | Tests against real files, including four processes at once. |

## How it works underneath

The database file is divided into pages. A **journal** protects it against a crash in the middle of a write. In the default mode a writer locks the whole file; in **WAL** mode (write-ahead log, `PRAGMA journal_mode = WAL`) writes go to a side file first, so readers are not blocked by a writer. Only one writer at a time is allowed either way.

`BEGIN IMMEDIATE` starts a transaction and takes the write lock at once. If another process holds it, SQLite waits up to the **busy timeout** and then raises an error ("database is locked"). `STRICT` tables enforce column types. Foreign keys are checked only when `PRAGMA foreign_keys = ON` is set on that connection.

Several processes can share one file on the same machine. Putting the file on a network share is unsafe.

## Walkthrough of this repository's use

### Opening the file

```python
    def __init__(self, path: Path) -> None:
        """Open `path` in autocommit mode; transactions are explicit (`BEGIN IMMEDIATE`)."""
        self._connection = sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
```

`isolation_level=None` turns off Python's automatic transactions, so the code controls `BEGIN` and `COMMIT` itself. `timeout=5.0` is the busy timeout: how long to wait for another writer's lock. `PRAGMA journal_mode = WAL` switches to write-ahead logging, so several processes can read while one writes. `PRAGMA foreign_keys = ON` turns on foreign-key checks for this connection.

### One transaction per command

```python
    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        """Write the command in one transaction; see the `Ledger` port."""
        try:
            self._connection.execute("BEGIN IMMEDIATE")  # take the write lock now, so the read below cannot go stale
        except sqlite3.OperationalError as error:
            raise TransientError(f"ledger is busy: {error}") from error
        try:
            if deduplicate:
                seen = (
                    self._connection.execute(
                        "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)", (message_id,)
                    ).rowcount
                    == 0
                )
                if seen:
                    self._connection.execute("COMMIT")
                    return ApplyResult(applied=False, previous_seq=0)
            previous_seq = self._connection.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE customer_id = ?", (command.customer_id,)
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES (?, ?, ?, ?, ?)",
                (command.order_id, command.customer_id, command.seq, command.amount_cents, delivery_count),
            )
            self._connection.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            self._connection.execute("ROLLBACK")
            raise UnknownCustomerError(command.customer_id) from error
        except sqlite3.OperationalError as error:
            self._connection.execute("ROLLBACK")
            raise TransientError(f"ledger error: {error}") from error
        return ApplyResult(applied=True, previous_seq=int(previous_seq))
```

`BEGIN IMMEDIATE` takes the write lock at once, so the later read of the customer's last sequence number cannot go stale. In idempotent mode `INSERT OR IGNORE INTO processed_messages ... rowcount == 0` means the message id was already there: nothing is written and the transaction commits empty. Otherwise the code reads `MAX(seq)` for the customer, inserts the ledger row and commits: the row and the message id become visible together or not at all. A foreign-key failure (`IntegrityError`) means an unknown customer: rollback, and raise a permanent error so the message is dead-lettered. `OperationalError` (database locked) is rolled back and raised as a transient error so the message is retried. The `?` marks are **placeholders**: the library passes the values separately from the statement, which prevents SQL injection.

### Setting up the file from the SQL scripts

```python
def prepare_database(path: Path, sql_dir: Path, *, with_migrations: bool) -> None:
    """Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql`.

    These are the same files `make db` and `make migrate` run with the sqlite3 shell; every statement is idempotent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    scripts = [sql_dir / "001_schema.sql", sql_dir / "002_seed.sql"]
    if with_migrations:
        scripts += sorted((sql_dir / "migrations").glob("*.sql"))
    connection = sqlite3.connect(path)
    try:
        for script in scripts:
            connection.executescript(script.read_text(encoding="utf-8"))
    finally:
        connection.close()
```

`executescript` runs a whole file of statements. The scripts are idempotent (`IF NOT EXISTS`, `INSERT OR IGNORE`), so running them again is harmless. The migrations are applied only in idempotent mode, because the naive mode must run without the `processed_messages` table.

### The same file with the shell

```make
db: ## apply sql/001_schema.sql and sql/002_seed.sql to $(DB)
	@mkdir -p $(dir $(DB))
	$(SQLITE) < sql/001_schema.sql
	$(SQLITE) < sql/002_seed.sql
```

`sqlite3 data/orders.db < sql/001_schema.sql` feeds a file to the `sqlite3` command-line shell, which executes it against that database file. `make queries` does the same with `sql/003_queries.sql`.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `src/order_worker/infrastructure/sqlite_ledger.py`

83 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The ledger in SQLite: one transaction per command, so the row and the message id commit together or not at all."""
```

**New idea.** A **transaction** groups several database changes so that they all happen or none does. `COMMIT` makes them permanent; `ROLLBACK` throws them away. Another reader never sees a half-finished transaction.

**New idea.** A **module** is one `.py` file. Python runs a file from the top to the bottom, once, the first time something imports it; `def` and `class` statements at the top level just create functions and classes, they do not run their bodies.

**New idea.** A **docstring** is a text in triple quotes as the very first statement of a module, class or function. It does nothing when the program runs; tools and people read it as the official description.

The module docstring says: The ledger in SQLite: one transaction per command, so the row and the message id commit together or not at all.

**Lines 3 to 5**

```python
import sqlite3
from collections.abc import Sequence
from pathlib import Path
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

What happens, step by step:

- `sqlite3`: the standard-library module for SQLite databases.
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.
- `Path` from `pathlib`: a file path as an object.

**Lines 7 to 10**

```python
from order_worker.application.ports import OrderRow
from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import TransientError, UnknownCustomerError
from order_worker.domain.processing import ApplyResult
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

What happens, step by step:

- `OrderRow` from the repository's own module `order_worker.application.ports`: One ledger row, in the order it was applied (defined in `src/order_worker/application/ports.py`)
- `OrderCommand` from the repository's own module `order_worker.domain.commands`: One order: who ordered, which order, the customer's sequence number and the amount in cents (defined in `src/order_worker/domain/commands.py`)
- `TransientError` from the repository's own module `order_worker.domain.errors`: A failure that a retry may fix (a busy database): the message is abandoned and delivered again (defined in `src/order_worker/domain/errors.py`)
- `UnknownCustomerError` from the repository's own module `order_worker.domain.errors`: The command names a customer that does not exist (defined in `src/order_worker/domain/errors.py`)
- `ApplyResult` from the repository's own module `order_worker.domain.processing`: What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write (defined in `src/order_worker/domain/processing.py`)

**Line 12**

```python
_BUSY_TIMEOUT_SECONDS = 5.0
```

What happens, step by step:

- Sets `_BUSY_TIMEOUT_SECONDS` to `5.0`.

**Lines 15 to 29**

```python
def prepare_database(path: Path, sql_dir: Path, *, with_migrations: bool) -> None:
    """Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql`.

    These are the same files `make db` and `make migrate` run with the sqlite3 shell; every statement is idempotent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    scripts = [sql_dir / "001_schema.sql", sql_dir / "002_seed.sql"]
    if with_migrations:
        scripts += sorted((sql_dir / "migrations").glob("*.sql"))
    connection = sqlite3.connect(path)
    try:
        for script in scripts:
            connection.executescript(script.read_text(encoding="utf-8"))
    finally:
        connection.close()
```

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

**New idea.** **UTF-8** is the standard way to store text as bytes, able to represent every language. A program that reads a file must decode the bytes with the right encoding to get text back.

The docstring in the code says: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql`. These are the same files `make db` and `make migrate` run with the sqlite3 shell; every statement is idempotent.

**Function `prepare_database`** takes `path` (type `Path`), `sql_dir` (type `Path`), `with_migrations` (by name only), type `bool`; gives back `None`.

**New idea.** A parameter written `name=value` has a **default**: if the caller leaves it out, the default is used.

**New idea.** A bare `*` in a parameter list means every parameter after it must be passed by name (`f(x=1)`) and cannot be passed by position. This prevents mixing up arguments.

**New idea.** A **type hint** such as `name: str` or `-> int` says what kind of value a parameter or result is. Python does not enforce hints when the program runs; the checker `mypy` reads them before the program runs and reports mismatches.

**New idea.** `def name(parameters):` defines a **function**: a named, reusable block of code. The indented lines under it are its body, which runs only when the function is **called** as `name(values)`. `return value` hands a result back to the caller; a function without `return` gives back `None`.

**New idea.** `if condition:` runs its block only when the condition is true; `elif` adds another test; `else` is what runs when none matched.

**New idea.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up.

**New idea.** `None` is Python's value for "nothing here". Functions that find nothing return it, and a parameter that defaults to `None` means "not given".

**New idea.** `x += 1` is shorthand for `x = x + 1`; `-=`, `*=` and `|=` work the same way.

**New idea.** `for item in things:` runs its block once for each element of `things`, with `item` set to that element.

**New idea.** `pathlib.Path` represents a file path as an object: `Path("a") / "b"` joins parts, `.read_text()` reads a file, `.exists()` tests for it.

What happens, step by step:

- Calls `path.parent.mkdir(parents=True, exist_ok=True)`.
- Sets `scripts` to `[sql_dir / '001_schema.sql', sql_dir / '002_seed.sql']`.
- If `with_migrations` is true:
  - Updates `scripts` with `=` `sorted((sql_dir / 'migrations').glob('*.sql'))`.
- Sets `connection` to the result of calling `sqlite3.connect(path)`.
- Try:
  - For each `script` in `scripts`:
    - Calls `connection.executescript(script.read_text(encoding='utf-8'))`.
- Always, in the end:
  - Calls `connection.close()`.

Names used here:

- `Path.mkdir()` creates a folder.
- `sorted(x)` returns a new list with the items in order.
- `Path.glob(pattern)` lists matching files.
- `connect` is the repository's own: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)
- `.executescript(sql)` runs several SQL statements written as one text.
- `Path.read_text()` reads a whole file as text.

**Lines 32 to 42**

```python
def is_reachable(path: Path) -> bool:
    """True when the ledger file opens and answers a query (used by the readiness probe)."""
    try:
        connection = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_SECONDS)
        try:
            connection.execute("SELECT 1 FROM ledger LIMIT 1").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return True
```

**New idea.** A **timeout** is the longest a program waits for something before giving up. Without one, a call to a service that never answers would make the program wait forever.

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

The docstring in the code says: True when the ledger file opens and answers a query (used by the readiness probe).

**Function `is_reachable`** takes `path` (type `Path`); gives back `bool`.

What happens, step by step:

- Try:
  - Sets `connection` to the result of calling `sqlite3.connect(path, timeout=_BUSY_TIMEOUT_SECONDS)`.
  - Try:
    - Calls `connection.execute('SELECT 1 FROM ledger LIMIT 1').fetchall()`.
  - Always, in the end:
    - Calls `connection.close()`.
- If `sqlite3.Error` is raised:
  - Returns `False`.
- Returns `True`.

Names used here:

- `.fetchall()` reads every remaining result row.
- `.execute(sql, values)` runs one SQL statement; `?` placeholders are filled from `values` safely.

**Lines 45 to 46**

```python
class SqliteLedger:
    """Implements the `Ledger` and `LedgerReader` ports. Several processes may share one file (WAL mode)."""
```

**New idea.** A **process** is one running copy of a program. The operating system gives it its own memory and a number, its *pid*. Two processes do not share variables; they cooperate through files, network connections or signals.

The docstring in the code says: Implements the `Ledger` and `LedgerReader` ports. Several processes may share one file (WAL mode).

**Class `SqliteLedger`**.

**New idea.** `class Name:` defines a **class**: a blueprint for objects that bundle data (attributes) with functions that work on it (methods). Calling the class, `Name(...)`, builds one object, an **instance**.

**Lines 48 to 52**

```python
    def __init__(self, path: Path) -> None:
        """Open `path` in autocommit mode; transactions are explicit (`BEGIN IMMEDIATE`)."""
        self._connection = sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
```

The docstring in the code says: Open `path` in autocommit mode; transactions are explicit (`BEGIN IMMEDIATE`).

**Method `__init__`** takes `path` (type `Path`); gives back `None`.

**New idea.** Inside a method, the first parameter, by convention `self`, is the object the method was called on. `self.value` reads or sets an attribute of that object.

**New idea.** `__init__` is the special method Python calls right after it creates an object; it sets the object's starting attributes. Names with double underscores on both sides are **dunder methods**: Python calls them for you in response to syntax (`__init__` on creation, `__repr__` when printing, `__len__` for `len(x)`, `__eq__` for `==`).

What happens, step by step:

- Sets `self._connection` to the result of calling `sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)`.
- Calls `self._connection.execute('PRAGMA journal_mode = WAL')`.
- Calls `self._connection.execute('PRAGMA foreign_keys = ON')`.

**Lines 54 to 55**

```python
    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        """Write the command in one transaction; see the `Ledger` port."""
```

The docstring in the code says: Write the command in one transaction; see the `Ledger` port.

**Method `apply`** takes `message_id` (type `str`), `command` (type `OrderCommand`), `delivery_count` (type `int`), `deduplicate` (by name only), type `bool`; gives back `ApplyResult`.

The body is split into the parts below.

**Lines 56 to 84**

```python
        try:
            self._connection.execute("BEGIN IMMEDIATE")  # take the write lock now, so the read below cannot go stale
        except sqlite3.OperationalError as error:
            raise TransientError(f"ledger is busy: {error}") from error
        try:
            if deduplicate:
                seen = (
                    self._connection.execute(
                        "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)", (message_id,)
                    ).rowcount
                    == 0
                )
                if seen:
                    self._connection.execute("COMMIT")
                    return ApplyResult(applied=False, previous_seq=0)
            previous_seq = self._connection.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE customer_id = ?", (command.customer_id,)
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES (?, ?, ?, ?, ?)",
                (command.order_id, command.customer_id, command.seq, command.amount_cents, delivery_count),
            )
            self._connection.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            self._connection.execute("ROLLBACK")
            raise UnknownCustomerError(command.customer_id) from error
        except sqlite3.OperationalError as error:
            self._connection.execute("ROLLBACK")
            raise TransientError(f"ledger error: {error}") from error
```

**New idea.** `raise Error(...)` stops the current function and signals a failure. `raise NewError(...) from error` also records the original error as the cause, so the traceback shows both.

**New idea.** An **f-string** is text written `f"...{value}..."`: whatever is inside the braces is evaluated and its text is put into the string. A format after a colon controls how: `{x:g}` prints a number without trailing zeros, `{x:.1f}` keeps one decimal, `{x!r}` uses the value's `repr`.

**New idea.** A **tuple** `(a, b)` is a fixed list of values. **Unpacking** `x, y = pair` assigns the parts to separate names in one statement.

What happens, step by step:

- Try:
  - Calls `self._connection.execute('BEGIN IMMEDIATE')`.
- If `sqlite3.OperationalError` is raised (the error is called `error`):
  - Raises `TransientError(f'ledger is busy: {error}')`, recording `error` as its cause.
- Try:
  - If `deduplicate` is true:
    - Sets `seen` to `self._connection.execute('INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)', (message_id,)).r…` (long; see the quote).
    - If `seen` is true:
      - Calls `self._connection.execute('COMMIT')`.
      - Returns `ApplyResult(applied=False, previous_seq=0)`.
  - Sets `previous_seq` to `self._connection.execute('SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE customer_id = ?', (command.customer_…` (long; see the quote).
  - Calls `self._connection.execute` with `'INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES (?, ?, ?, ?, ?)'`; `(command.order_id, command.customer_id, command.seq, command.amount_cents, delivery_count)`.
  - Calls `self._connection.execute('COMMIT')`.
- If `sqlite3.IntegrityError` is raised (the error is called `error`):
  - Calls `self._connection.execute('ROLLBACK')`.
  - Raises `UnknownCustomerError(command.customer_id)`, recording `error` as its cause.
- If `sqlite3.OperationalError` is raised (the error is called `error`):
  - Calls `self._connection.execute('ROLLBACK')`.
  - Raises `TransientError(f'ledger error: {error}')`, recording `error` as its cause.

Names used here:

- `.fetchone()` reads the next result row, or `None`.

**Line 85**

```python
        return ApplyResult(applied=True, previous_seq=int(previous_seq))
```

What happens, step by step:

- Returns `ApplyResult(applied=True, previous_seq=int(previous_seq))`.

Names used here:

- `int(x)` turns a value into a whole number.

**Lines 87 to 93**

```python
    def rows(self) -> Sequence[OrderRow]:
        """Every ledger row in apply order."""
        cursor = self._connection.execute(
            "SELECT apply_order, order_id, customer_id, seq, amount_cents, delivery_count "
            "FROM ledger ORDER BY apply_order"
        )
        return [OrderRow(*row) for row in cursor.fetchall()]
```

The docstring in the code says: Every ledger row in apply order.

**Method `rows`** takes no parameters; gives back `Sequence[OrderRow]`.

**New idea.** Square brackets after a type, as in `list[str]` or `dict[str, int]`, say what the container holds: a list of text, or a dictionary from text to whole numbers.

**New idea.** A **comprehension** builds a list, set or dictionary in one expression: `[f(x) for x in things if keep(x)]` means "for each `x` in `things` that passes `keep`, take `f(x)`". With braces and `key: value` it builds a dictionary.

**New idea.** `*items` in a call or list spreads the elements of `items` out as separate values; `**mapping` spreads a dictionary out as named arguments.

What happens, step by step:

- Sets `cursor` to the result of calling `self._connection.execute` with `'SELECT apply_order, order_id, customer_id, seq, amount_cents, delivery_count FROM ledger ORDER BY apply_orde…` (long; see the quote).
- Returns `[OrderRow(*row) for row in cursor.fetchall()]`.

**Lines 95 to 97**

```python
    def close(self) -> None:
        """Close the connection."""
        self._connection.close()
```

The docstring in the code says: Close the connection.

**Method `close`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._connection.close()`.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `tests/integration/test_sqlite_ledger.py` | 3, 14, 34 to 36, 42 to 43, 72, 79, 87, 90, 111, 138 to 140, 146 | [pytest.md](pytest.md) |
| `Makefile` | 10, 51 | [make.md](make.md) |
| `pyproject.toml` | 96 | [pyproject-toml.md](pyproject-toml.md) |
| `sql/003_queries.sql` | 1 | [sql.md](sql.md) |
| `sql/reset.sql` | 3 | [sql.md](sql.md) |
| `src/order_worker/infrastructure/scenarios.py` | 18 | [python.md](python.md) |
| `src/order_worker/interfaces/check_cli.py` | 9 | [python.md](python.md) |
| `src/order_worker/interfaces/worker_cli.py` | 14 | [python.md](python.md) |
| `tests/e2e/test_lesson_scenarios.py` | 17 | [pytest.md](pytest.md) |
| `tests/unit/interfaces/test_clis.py` | 10 | [pytest.md](pytest.md) |

## Try it yourself

Check the shell's SQLite version.

```bash
sqlite3 --version
```

You should see something like this:

```text
3.51.0 2025-06-12 13:14:41 f0ca7bba1c5e232e5d279fad6338121ab55af0c8c68c84cdfb18ba5114dcaapl (64-bit)
```

Build a database from the scripts and list its tables.

```bash
rm -f /tmp/tech-demo.db && sqlite3 /tmp/tech-demo.db < sql/001_schema.sql && sqlite3 /tmp/tech-demo.db < sql/002_seed.sql && sqlite3 /tmp/tech-demo.db 'SELECT COUNT(*) FROM customers; SELECT name FROM sqlite_master WHERE type="table" ORDER BY name;'
```

You should see something like this:

```text
20
customers
ledger
sqlite_sequence
```

Switch the file to WAL mode and read the mode back.

```bash
sqlite3 /tmp/tech-demo.db 'PRAGMA journal_mode = WAL; PRAGMA journal_mode;'
```

You should see something like this:

```text
wal
wal
```

Run the real-file tests, including four concurrent processes.

```bash
.venv/bin/python -m pytest tests/integration -q -p no:cacheprovider -m integration
```

You should see something like this:

```text
...........                                                              [100%]
11 passed, 1 deselected in 5.12s
```

## Mistakes people make

- Forgetting `PRAGMA foreign_keys = ON`, so foreign keys are not enforced.
- Sharing the file between machines over a network drive.
- Holding a write transaction open while doing slow work, which blocks other writers. This repository does its slow work (the deliberate 45-second sleep) before the transaction.
- Treating a `database is locked` error as fatal. Here it becomes a transient error and the message is retried.
- Expecting several replicas to share one local file. In the container each replica has its own.

## Check yourself

1. **Where does an SQLite database live?**
   Answer: In a single file; there is no server process.

2. **What does WAL mode change?**
   Answer: Writes go to a log file first, so readers are not blocked by a writer.

3. **What does `BEGIN IMMEDIATE` do?**
   Answer: Starts a transaction and takes the write lock right away.

4. **How many writers can SQLite have at once?**
   Answer: One.

5. **Why must `PRAGMA foreign_keys = ON` be set on each connection?**
   Answer: The setting is per connection and defaults to off.

## Further reading

- SQLite 3.51 documentation: https://www.sqlite.org/docs.html
- WAL mode: https://www.sqlite.org/wal.html
- STRICT tables: https://www.sqlite.org/stricttables.html
- Python `sqlite3`: https://docs.python.org/3.13/library/sqlite3.html
