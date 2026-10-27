"""The lesson's checks, one test each, on the simulated broker and a real SQLite ledger."""

import json
import subprocess
import sys

import pytest

from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.ports import OutgoingMessage
from order_worker.application.run_worker import RunWorker
from order_worker.domain.commands import parse_command
from order_worker.domain.errors import TransientError
from order_worker.domain.processing import ApplyResult, Mode
from order_worker.infrastructure.scenarios import run_duplicates, run_ordering, run_poison_and_replay
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database

pytestmark = pytest.mark.e2e


def test_step_1_a_thousand_commands_end_up_in_the_database_exactly_as_expected(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE, slow_every=0)
    assert (result.report.rows, result.report.total) == (1000, 10000.0)
    assert result.problems == []


def test_step_2_lock_expiry_delivers_one_command_in_ten_twice_and_the_database_shows_the_duplicate_effect(
    database, sql_dir
):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE)
    assert (result.report.rows, result.report.total) == (1100, 11000.0)
    assert result.max_delivery_count == 2
    assert result.stats.lock_lost == 100
    assert len(result.report.duplicate_orders) == 100
    assert "duplicate effect for order o-c01-010" in result.problems


def test_step_3_idempotence_alone_removes_the_duplicate_effect_but_not_the_lost_locks(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT)
    assert result.problems == []
    assert (result.stats.skipped_duplicates, result.stats.lock_lost) == (100, 100)


def test_step_3_lock_renewal_alone_prevents_the_redelivery_in_this_run(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.NAIVE, lock_renewal_seconds=300)
    assert result.problems == []
    assert (result.max_delivery_count, result.stats.lock_lost) == (1, 0)


def test_step_3_both_together_give_the_clean_run_with_no_lock_errors(database, sql_dir):
    result = run_duplicates(database, sql_dir, mode=Mode.IDEMPOTENT, lock_renewal_seconds=300)
    assert result.problems == []
    assert (result.stats.skipped_duplicates, result.stats.lock_lost) == (0, 0)


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


def test_step_4_without_sessions_a_stalled_worker_lets_a_customers_commands_be_applied_out_of_order(database, sql_dir):
    result = run_ordering(database, sql_dir, sessions=False)
    assert result.report.rows == 1000
    assert result.report.out_of_order, "the check must see the reordering"
    assert any("c01" in line for line in result.report.out_of_order)


def test_step_4_with_sessions_every_customers_commands_apply_in_order_even_with_a_stalled_worker(database, sql_dir):
    result = run_ordering(database, sql_dir, sessions=True)
    assert result.problems == []
    assert result.report.out_of_order == ()


def test_step_4_more_workers_keep_the_order_when_sessions_are_on(database, sql_dir):
    assert run_ordering(database, sql_dir, sessions=True, workers=7, stall_rounds=25).problems == []


def test_step_5_the_poison_command_goes_to_the_dead_letter_queue_with_a_reason_and_the_rest_flows(database, sql_dir):
    result = run_poison_and_replay(database, sql_dir)
    assert result.dead_letters_before == [("o-bad", "InvalidAmount", "amount is not a number")]
    assert result.ledger_rows_before == 1000


def test_step_6_the_fixed_command_is_processed_once_even_if_the_tool_runs_twice(database, sql_dir):
    result = run_poison_and_replay(database, sql_dir)
    assert (result.replay.fixed, result.second_replay.fixed) == (1, 0)
    assert result.o_bad_rows == 1
    assert result.after.report.rows == 1001
    assert result.after.problems == []
    assert result.after.dead_letters == []


def test_step_6_the_replay_keeps_the_session_so_the_fixed_command_lands_after_the_customers_earlier_ones(
    database, sql_dir
):
    result = run_poison_and_replay(database, sql_dir, sessions=True)
    assert result.o_bad_rows == 1
    assert result.after.problems == []


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
