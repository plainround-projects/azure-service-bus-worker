import json
import logging

import pytest

from order_worker.application.handle_delivery import Effect, HandleDelivery
from order_worker.domain.processing import Chaos, Mode
from tests.unit.application.fakes import FakeClock, FakeDelivery, FakeLedger, transient, unknown_customer


def _command(seq: int = 1, amount: object = 10.0, customer: str = "c01") -> bytes:
    return json.dumps(
        {"orderId": f"o-{customer}-{seq:03d}", "customerId": customer, "seq": seq, "amount": amount}
    ).encode()


def test_the_message_is_completed_only_after_the_ledger_write():
    events: list[str] = []
    ledger = FakeLedger(events)
    delivery = FakeDelivery(_command(), events=events)
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert events == ["apply:o-c01-001", "settle:complete"]
    assert (handled.effect, handled.settled) == (Effect.APPLIED, True)


def test_a_crash_inside_the_write_leaves_the_message_unsettled_so_the_queue_redelivers_it():
    ledger = FakeLedger()
    ledger.raise_error = RuntimeError("process killed")
    delivery = FakeDelivery(_command())
    with pytest.raises(RuntimeError):
        HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert delivery.settled == []


def test_the_idempotent_mode_asks_the_ledger_to_deduplicate_and_the_naive_mode_does_not():
    for mode, expected in ((Mode.IDEMPOTENT, True), (Mode.NAIVE, False)):
        ledger = FakeLedger()
        HandleDelivery(ledger, FakeClock(), mode).handle(FakeDelivery(_command()))
        assert ledger.calls[0][3] is expected


def test_a_repeated_message_is_skipped_but_still_completed():
    ledger = FakeLedger()
    handler = HandleDelivery(ledger, FakeClock())
    handler.handle(FakeDelivery(_command(), message_id="same"))
    second = FakeDelivery(_command(), message_id="same", delivery_count=2)
    handled = handler.handle(second)
    assert handled.effect is Effect.SKIPPED_DUPLICATE
    assert second.settled == ["complete"]


def test_a_poison_message_is_dead_lettered_at_once_with_its_reason_and_description():
    ledger = FakeLedger()
    delivery = FakeDelivery(_command(amount="abc"))
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert handled.effect is Effect.DEAD_LETTERED
    assert delivery.settled == ["dead-letter:InvalidAmount:amount is not a number"]
    assert ledger.calls == []  # nothing was written


def test_a_command_the_ledger_can_never_accept_is_dead_lettered_too():
    ledger = FakeLedger()
    ledger.raise_error = unknown_customer()
    delivery = FakeDelivery(_command(customer="c99"))
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert handled.effect is Effect.DEAD_LETTERED
    assert delivery.settled[0].startswith("dead-letter:UnknownCustomer")


def test_a_transient_failure_abandons_the_message_so_it_is_tried_again():
    ledger = FakeLedger()
    ledger.raise_error = transient()
    delivery = FakeDelivery(_command())
    handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert (handled.effect, delivery.settled) == (Effect.ABANDONED, ["abandon"])


def test_a_lost_lock_on_complete_is_logged_not_raised_and_the_effect_stands(caplog):
    ledger = FakeLedger()
    delivery = FakeDelivery(_command(), lock_lost=True)
    with caplog.at_level(logging.WARNING, logger="order_worker.handler"):
        handled = HandleDelivery(ledger, FakeClock()).handle(delivery)
    assert (handled.effect, handled.settled) == (Effect.APPLIED, False)
    assert "complete failed for o-c01-001: the lock supplied is invalid" in caplog.text


def test_a_lost_lock_on_dead_letter_and_on_abandon_is_also_tolerated():
    poison = FakeDelivery(_command(amount="abc"), lock_lost=True)
    assert HandleDelivery(FakeLedger(), FakeClock()).handle(poison).settled is False
    ledger = FakeLedger()
    ledger.raise_error = transient()
    busy = FakeDelivery(_command(), lock_lost=True)
    assert HandleDelivery(ledger, FakeClock()).handle(busy).settled is False


def test_chaos_sleeps_before_the_write_on_the_first_delivery_only():
    clock = FakeClock()
    handler = HandleDelivery(FakeLedger(), clock, chaos=Chaos(slow_every=10, slow_seconds=45))
    handler.handle(FakeDelivery(_command(seq=10), delivery_count=1))
    handler.handle(FakeDelivery(_command(seq=10), delivery_count=2, message_id="m-2"))
    handler.handle(FakeDelivery(_command(seq=11), message_id="m-3"))
    assert clock.slept == [45.0]


def test_the_log_shows_the_lessons_apply_line_with_the_sleep_note(caplog):
    with caplog.at_level(logging.INFO, logger="order_worker.handler"):
        HandleDelivery(FakeLedger(), FakeClock(), chaos=Chaos(slow_every=10)).handle(FakeDelivery(_command(seq=10)))
    assert "apply o-c01-010 delivery_count=1 (sleeping 45 s)" in caplog.text


def test_a_command_applied_out_of_order_is_logged_as_an_error_and_still_applied(caplog):
    ledger = FakeLedger()
    ledger.previous_seq = 14  # the customer already has seq 14, and this is seq 10
    with caplog.at_level(logging.ERROR, logger="order_worker.handler"):
        handled = HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))
    assert handled.effect is Effect.APPLIED
    assert "out of order: customer c01 applied seq 10 after seq 14" in caplog.text


def test_a_command_that_follows_its_predecessor_logs_no_out_of_order(caplog):
    ledger = FakeLedger()
    ledger.previous_seq = 9
    with caplog.at_level(logging.ERROR, logger="order_worker.handler"):
        HandleDelivery(ledger, FakeClock()).handle(FakeDelivery(_command(seq=10)))
    assert "out of order" not in caplog.text
