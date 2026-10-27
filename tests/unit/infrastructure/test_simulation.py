"""The simulated broker must behave like Service Bus where the lesson depends on it."""

import pytest

from order_worker.application.ports import OutgoingMessage
from order_worker.domain.errors import LockLostError
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker


def _broker(**kwargs):
    clock = ManualClock()
    broker = SimulatedBroker(clock, **kwargs)
    return clock, broker


def _send(broker, *ids, session=None):
    broker.send([OutgoingMessage("{}", message_id, session) for message_id in ids])


def test_a_received_message_is_hidden_from_other_receivers_while_locked():
    _, broker = _broker()
    _send(broker, "a")
    first = broker.inbox().open().receive(1)
    assert first is not None
    assert first.delivery_count == 1
    assert broker.inbox().open().receive(1) is None
    assert broker.counts().locked == 1


def test_complete_inside_the_lock_removes_the_message():
    _, broker = _broker()
    _send(broker, "a")
    broker.inbox().open().receive(1).complete()
    assert (broker.counts().active, broker.counts().locked) == (0, 0)


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


def test_complete_after_expiry_fails_even_when_nobody_took_the_message_again():
    clock, broker = _broker()
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(31)
    with pytest.raises(LockLostError):
        delivery.complete()


def test_auto_renewal_keeps_the_lock_valid_for_slow_work():
    clock, broker = _broker(auto_renew_seconds=300)
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(45)
    delivery.complete()
    assert broker.counts().active == 0


def test_auto_renewal_ends_after_its_maximum():
    clock, broker = _broker(auto_renew_seconds=60)
    _send(broker, "a")
    delivery = broker.inbox().open().receive(1)
    clock.sleep(61)
    with pytest.raises(LockLostError):
        delivery.complete()


def test_abandon_makes_the_message_available_at_once():
    _, broker = _broker()
    _send(broker, "a")
    receiver = broker.inbox().open()
    receiver.receive(1).abandon()
    assert receiver.receive(1).delivery_count == 2


def test_a_message_delivered_the_maximum_number_of_times_goes_to_the_dead_letter_queue():
    _, broker = _broker(max_delivery_count=3)
    _send(broker, "a")
    receiver = broker.inbox().open()
    for _ in range(3):
        receiver.receive(1).abandon()
    assert receiver.receive(1) is None
    assert broker.dead_letter_reasons()[0][:2] == ("a", "MaxDeliveryCountExceeded")
    assert broker.max_delivery_seen() == 3


def test_explicit_dead_lettering_records_reason_and_description_and_other_messages_keep_flowing():
    _, broker = _broker()
    _send(broker, "bad", "good")
    receiver = broker.inbox().open()
    receiver.receive(1).dead_letter("InvalidAmount", "amount is not a number")
    assert receiver.receive(1).message_id == "good"
    assert broker.dead_letter_reasons() == [("bad", "InvalidAmount", "amount is not a number")]


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


def test_a_dead_letter_cannot_be_dead_lettered_again():
    _, broker = _broker()
    _send(broker, "bad")
    broker.inbox().open().receive(1).dead_letter("x", "y")
    dead = broker.dead_letters().open().receive(1)
    with pytest.raises(NotImplementedError):
        dead.dead_letter("a", "b")


def test_an_empty_receive_waits_so_virtual_time_passes():
    clock, broker = _broker()
    assert broker.inbox().open().receive(10) is None
    assert clock.now() == 10


def test_a_session_queue_refuses_a_message_without_a_session_id():
    _, broker = _broker(sessions=True)
    with pytest.raises(ValueError, match="session"):
        _send(broker, "a")


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


def test_closing_a_session_receiver_releases_the_session():
    _, broker = _broker(sessions=True)
    _send(broker, "a1", session="c01")
    inbox = broker.inbox()
    first = inbox.open()
    assert inbox.open() is None
    first.close()
    assert inbox.open() is not None
