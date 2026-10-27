"""The real SQLite ledger on disk: transactions, the unique key that deduplicates, and several processes at once."""

import sqlite3
import subprocess
import sys
import textwrap
from contextlib import closing
from pathlib import Path

import pytest

from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import TransientError, UnknownCustomerError
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, is_reachable, prepare_database

pytestmark = pytest.mark.integration


def _command(n: int, customer: str = "c01") -> OrderCommand:
    return OrderCommand(f"o-{customer}-{n:03d}", customer, n, 1000)


@pytest.fixture
def ledger(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    instance = SqliteLedger(database)
    yield instance
    instance.close()


def test_preparing_the_database_twice_is_harmless_and_seeds_twenty_customers(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=True)
    prepare_database(database, sql_dir, with_migrations=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone() == (20,)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"customers", "ledger", "processed_messages"} <= tables


def test_without_the_migration_the_idempotency_table_does_not_exist(database, sql_dir):
    prepare_database(database, sql_dir, with_migrations=False)
    with closing(sqlite3.connect(database)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "processed_messages" not in tables


def test_the_ledger_has_no_unique_key_on_the_order_id_so_the_naive_mode_can_write_a_duplicate(ledger):
    first = ledger.apply("m-1", _command(1), 1, deduplicate=False)
    second = ledger.apply("m-1", _command(1), 2, deduplicate=False)
    assert first.applied
    assert second.applied
    assert [row.delivery_count for row in ledger.rows()] == [1, 2]


def test_the_idempotent_mode_writes_once_and_skips_the_repeat(ledger):
    assert ledger.apply("m-1", _command(1), 1, deduplicate=True).applied
    repeat = ledger.apply("m-1", _command(1), 2, deduplicate=True)
    assert repeat.applied is False
    assert len(ledger.rows()) == 1


def test_the_previous_sequence_is_the_customers_highest_applied_before_the_write(ledger):
    assert ledger.apply("m-1", _command(1), 1, deduplicate=True).previous_seq == 0
    assert ledger.apply("m-2", _command(2), 1, deduplicate=True).previous_seq == 1
    assert ledger.apply("m-9", _command(9), 1, deduplicate=True).previous_seq == 2
    assert ledger.apply("m-x", _command(1, "c02"), 1, deduplicate=True).previous_seq == 0


def test_an_unknown_customer_is_a_permanent_error_and_the_message_id_is_not_recorded(ledger, database):
    with pytest.raises(UnknownCustomerError):
        ledger.apply("m-bad", _command(1, "c99"), 1, deduplicate=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM processed_messages").fetchone() == (0,)
    assert ledger.rows() == []  # rolled back, so a later fix of the customer table could still process it


def test_amounts_are_stored_as_integer_cents(ledger, database):
    ledger.apply("m-1", OrderCommand("o-1", "c01", 1, 1999), 1, deduplicate=True)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT amount_cents, typeof(amount_cents) FROM ledger").fetchone() == (
            1999,
            "integer",
        )


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


def test_the_readiness_check_follows_the_file(database, sql_dir, tmp_path):
    assert is_reachable(tmp_path / "missing" / "nope.db") is False
    prepare_database(database, sql_dir, with_migrations=True)
    assert is_reachable(database) is True


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
