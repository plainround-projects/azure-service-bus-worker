import contextlib
import json

from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.run_worker import RunWorker
from tests.unit.application.fakes import FakeClock, FakeDelivery, FakeInbox, FakeLedger, ScriptedReceiver


def _delivery(seq: int, message_id: str | None = None) -> FakeDelivery:
    body = json.dumps({"orderId": f"o-{seq}", "customerId": "c01", "seq": seq, "amount": 10.0}).encode()
    return FakeDelivery(body, message_id=message_id or f"m-{seq}")


def _worker(inbox, clock=None, heartbeat=None):
    clock = clock or FakeClock()
    kwargs = {"heartbeat": heartbeat} if heartbeat else {}
    return RunWorker(inbox, HandleDelivery(FakeLedger(), clock), clock, max_wait_seconds=10.0, **kwargs)


def test_it_handles_every_delivery_and_counts_the_effects():
    clock = FakeClock()
    receiver = ScriptedReceiver([_delivery(1), _delivery(2), _delivery(2, "m-2")], clock)
    stats = _worker(FakeInbox(receiver), clock).run(until_idle_seconds=5)
    assert (stats.received, stats.applied, stats.skipped_duplicates) == (3, 2, 1)


def test_it_stops_after_the_idle_period_with_no_messages():
    clock = FakeClock()
    inbox = FakeInbox(*[ScriptedReceiver([], clock) for _ in range(10)])
    stats = _worker(inbox, clock).run(until_idle_seconds=25)
    assert stats.received == 0
    assert 25 <= clock.time < 45  # three empty passes of 10 s each


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


def test_it_stops_after_the_message_budget():
    receiver = ScriptedReceiver([_delivery(n) for n in range(1, 6)])
    stats = _worker(FakeInbox(receiver)).run(max_messages=3)
    assert stats.received == 3
    assert receiver.closed == 1


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


def test_it_beats_the_heart_on_every_pass_and_every_message():
    beats: list[int] = []
    receiver = ScriptedReceiver([_delivery(1), _delivery(2)])
    _worker(FakeInbox(receiver), heartbeat=lambda: beats.append(1)).run(max_messages=2)
    assert len(beats) >= 3


def test_a_lost_lock_is_counted():
    lost = _delivery(1)
    lost.lock_lost = True
    stats = _worker(FakeInbox(ScriptedReceiver([lost]))).run(max_messages=1)
    assert (stats.applied, stats.lock_lost) == (1, 1)


def test_dead_lettered_and_abandoned_deliveries_are_counted():
    bad = FakeDelivery(b"not json", message_id="bad")
    ledger = FakeLedger()
    clock = FakeClock()
    worker = RunWorker(FakeInbox(ScriptedReceiver([bad])), HandleDelivery(ledger, clock), clock)
    assert worker.run(max_messages=1).dead_lettered == 1


def test_when_no_receiver_can_be_opened_it_waits_instead_of_spinning():
    clock = FakeClock()
    stats = _worker(FakeInbox(), clock).run(until_idle_seconds=25)
    assert stats.received == 0
    assert clock.slept == [10.0, 10.0, 10.0, 10.0]
