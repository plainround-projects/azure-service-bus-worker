"""The ledger in SQLite: one transaction per command, so the row and the message id commit together or not at all."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from order_worker.application.ports import OrderRow
from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import TransientError, UnknownCustomerError
from order_worker.domain.processing import ApplyResult

_BUSY_TIMEOUT_SECONDS = 5.0


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


class SqliteLedger:
    """Implements the `Ledger` and `LedgerReader` ports. Several processes may share one file (WAL mode)."""

    def __init__(self, path: Path) -> None:
        """Open `path` in autocommit mode; transactions are explicit (`BEGIN IMMEDIATE`)."""
        self._connection = sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")

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

    def rows(self) -> Sequence[OrderRow]:
        """Every ledger row in apply order."""
        cursor = self._connection.execute(
            "SELECT apply_order, order_id, customer_id, seq, amount_cents, delivery_count "
            "FROM ledger ORDER BY apply_order"
        )
        return [OrderRow(*row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the connection."""
        self._connection.close()
