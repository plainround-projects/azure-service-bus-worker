"""The Service Bus adapter against stubs of the SDK objects: the calls it makes and the errors it translates."""

from types import SimpleNamespace
from typing import Any

import pytest
from azure.servicebus import NEXT_AVAILABLE_SESSION, ServiceBusSubQueue
from azure.servicebus.exceptions import (
    MessageLockLostError,
    OperationTimeoutError,
    ServiceBusConnectionError,
    SessionLockLostError,
)

from order_worker.application.ports import OutgoingMessage
from order_worker.domain.errors import LockLostError
from order_worker.infrastructure.servicebus import ServiceBusMessaging, _SdkDelivery, _SdkReceiver
from order_worker.infrastructure.settings import ConfigError, Settings
from order_worker.infrastructure.wiring import connect


class _Credential:
    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        raise AssertionError("no network in unit tests")


class _SdkReceiverStub:
    def __init__(self, messages=(), error=None) -> None:
        self.messages = list(messages)
        self.error = error
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    def receive_messages(self, max_message_count, max_wait_time):
        self.calls.append(("receive", (max_message_count, max_wait_time)))
        if self.error:
            raise self.error
        return [self.messages.pop(0)] if self.messages else []

    def complete_message(self, message):
        self.calls.append(("complete", message))
        if self.error:
            raise self.error

    def abandon_message(self, message):
        self.calls.append(("abandon", message))
        if self.error:
            raise self.error

    def dead_letter_message(self, message, reason, error_description):
        self.calls.append(("dead_letter", (reason, error_description)))
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


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


def test_a_delivery_exposes_the_message_fields():
    delivery = _SdkDelivery(_SdkReceiverStub(), _message())  # type: ignore[arg-type]
    assert delivery.message_id == "o-1"
    assert delivery.body == b'{"a":1}'
    assert (delivery.delivery_count, delivery.session_id) == (2, "c01")
    assert (delivery.dead_letter_reason, delivery.dead_letter_description) == (
        "InvalidAmount",
        "amount is not a number",
    )


def test_a_missing_delivery_count_means_the_first_delivery():
    assert _SdkDelivery(_SdkReceiverStub(), _message(delivery_count=None)).delivery_count == 1  # type: ignore[arg-type]


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


def test_the_receiver_asks_for_one_message_and_wraps_it():
    stub = _SdkReceiverStub([_message()])
    receiver = _SdkReceiver(stub, None)  # type: ignore[arg-type]
    delivery = receiver.receive(7)
    assert delivery is not None
    assert delivery.message_id == "o-1"
    assert stub.calls[0] == ("receive", (1, 7))
    assert receiver.receive(7) is None


def test_a_session_receiver_with_no_session_to_lock_returns_none():
    receiver = _SdkReceiver(_SdkReceiverStub(error=OperationTimeoutError(message="no session")), None)  # type: ignore[arg-type]
    assert receiver.receive(1) is None


def test_closing_the_receiver_closes_the_lock_renewer_too():
    closed = []
    renewer = SimpleNamespace(close=lambda: closed.append("renewer"))
    stub = _SdkReceiverStub()
    _SdkReceiver(stub, renewer).close()  # type: ignore[arg-type]
    assert stub.closed
    assert closed == ["renewer"]


class _ClientStub:
    def __init__(self) -> None:
        self.receivers: list[dict[str, Any]] = []
        self.sent: list[Any] = []
        self.batch_limit = 3
        self.closed = False

    def get_queue_receiver(self, queue, **kwargs):
        self.receivers.append({"queue": queue, **kwargs})
        return _SdkReceiverStub()

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

    def close(self):
        self.closed = True


def _messaging():
    messaging = ServiceBusMessaging("mybus.servicebus.windows.net", "orders", _Credential())  # type: ignore[arg-type]
    messaging._client = _ClientStub()  # type: ignore[assignment]
    return messaging, messaging._client


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


def test_without_renewal_no_renewer_is_created():
    messaging, client = _messaging()
    messaging.inbox(sessions=False, max_wait_seconds=10, lock_renewal_seconds=0).open()
    assert client.receivers[0]["auto_lock_renewer"] is None


def test_a_session_inbox_asks_for_the_next_available_session():
    messaging, client = _messaging()
    messaging.inbox(sessions=True, max_wait_seconds=10, lock_renewal_seconds=0).open()
    assert client.receivers[0]["session_id"] == NEXT_AVAILABLE_SESSION


def test_the_dead_letter_inbox_reads_the_dead_letter_sub_queue_and_never_uses_sessions():
    messaging, client = _messaging()
    messaging.dead_letters(max_wait_seconds=5).open()
    options = client.receivers[0]
    assert options["sub_queue"] == ServiceBusSubQueue.DEAD_LETTER
    assert options["session_id"] is None


def test_the_sender_starts_a_new_batch_when_one_is_full_and_sends_the_remainder():
    messaging, client = _messaging()
    messages = [OutgoingMessage("{}", f"m-{n}", "c01") for n in range(7)]
    messaging.sender().send(messages)
    assert [len(batch) for batch in client.sent] == [3, 3, 1]
    assert client.sent[0][0].message_id == "m-0"
    assert client.sent[0][0].session_id == "c01"


def test_the_context_manager_closes_the_connection():
    messaging, client = _messaging()
    with messaging:
        pass
    assert client.closed


def test_connect_builds_a_client_without_contacting_azure_and_needs_a_namespace():
    settings = Settings.from_env(
        {"SB_NAMESPACE": "mybus.servicebus.windows.net", "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000000"}
    )
    with connect(settings) as messaging:
        assert messaging.inbox(sessions=False, max_wait_seconds=1, lock_renewal_seconds=0) is not None
    with pytest.raises(ConfigError):
        connect(Settings.from_env({}, require_namespace=False))
