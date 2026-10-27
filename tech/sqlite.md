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
