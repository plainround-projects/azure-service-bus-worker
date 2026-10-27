"""The Azure Service Bus adapters. They authenticate with `DefaultAzureCredential` and nothing else."""

from collections.abc import Sequence
from types import TracebackType

from azure.identity import DefaultAzureCredential
from azure.servicebus import (
    NEXT_AVAILABLE_SESSION,
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusMessage,
    ServiceBusReceivedMessage,
    ServiceBusReceiver,
    ServiceBusSubQueue,
)
from azure.servicebus.exceptions import (
    MessageLockLostError,
    OperationTimeoutError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    SessionLockLostError,
)

from order_worker.application.ports import Delivery, OutgoingMessage, Receiver
from order_worker.domain.errors import LockLostError

_RETRY_TOTAL = 3
_UNSETTLED = (
    MessageLockLostError,
    SessionLockLostError,
    ServiceBusConnectionError,
    ServiceBusCommunicationError,
    OperationTimeoutError,
)


class _SdkDelivery:
    """A received message and the receiver that holds its lock."""

    def __init__(self, receiver: ServiceBusReceiver, message: ServiceBusReceivedMessage) -> None:
        self._receiver = receiver
        self._message = message

    @property
    def message_id(self) -> str:
        return str(self._message.message_id)

    @property
    def body(self) -> bytes:
        return b"".join(bytes(part) for part in self._message.body)

    @property
    def delivery_count(self) -> int:
        return int(self._message.delivery_count or 1)

    @property
    def session_id(self) -> str | None:
        return self._message.session_id

    @property
    def dead_letter_reason(self) -> str | None:
        return self._message.dead_letter_reason

    @property
    def dead_letter_description(self) -> str | None:
        return self._message.dead_letter_error_description

    def complete(self) -> None:
        try:
            self._receiver.complete_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error

    def abandon(self) -> None:
        try:
            self._receiver.abandon_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error

    def dead_letter(self, reason: str, description: str) -> None:
        try:
            self._receiver.dead_letter_message(self._message, reason=reason, error_description=description)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error


class _SdkReceiver:
    def __init__(self, receiver: ServiceBusReceiver, renewer: AutoLockRenewer | None) -> None:
        self._receiver = receiver
        self._renewer = renewer

    def receive(self, max_wait_seconds: float) -> Delivery | None:
        try:
            messages = self._receiver.receive_messages(max_message_count=1, max_wait_time=max_wait_seconds)
        except OperationTimeoutError:  # a session receiver found no session with messages within the wait
            return None
        return _SdkDelivery(self._receiver, messages[0]) if messages else None

    def close(self) -> None:
        self._receiver.close()
        if self._renewer is not None:
            self._renewer.close()


class ServiceBusMessaging:
    """One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue."""

    def __init__(self, namespace: str, queue: str, credential: DefaultAzureCredential) -> None:
        """Connect lazily to `namespace` (for example mybus.servicebus.windows.net)."""
        self._queue = queue
        self._client = ServiceBusClient(namespace, credential, retry_total=_RETRY_TOTAL)

    def __enter__(self) -> "ServiceBusMessaging":
        """Use as a context manager so the connection is closed."""
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Close the connection."""
        self._client.close()

    def inbox(self, *, sessions: bool, max_wait_seconds: float, lock_renewal_seconds: int) -> "_Inbox":
        """Receivers for the main queue. With `sessions`, each receiver locks the next session that has messages.

        With `lock_renewal_seconds` above zero, locks are renewed in the background for up to that long (lesson step 3).
        """
        return _Inbox(self._client, self._queue, sessions, False, max_wait_seconds, lock_renewal_seconds)

    def dead_letters(self, *, max_wait_seconds: float) -> "_Inbox":
        """Receivers for the queue's dead-letter sub-queue. It is never session-aware, even on a session queue."""
        return _Inbox(self._client, self._queue, False, True, max_wait_seconds, 0)

    def sender(self) -> "_Sender":
        """A sender for the main queue."""
        return _Sender(self._client, self._queue)


class _Inbox:
    def __init__(
        self,
        client: ServiceBusClient,
        queue: str,
        sessions: bool,
        dead_letter: bool,
        max_wait_seconds: float,
        lock_renewal_seconds: int,
    ) -> None:
        self._client, self._queue = client, queue
        self._sessions, self._dead_letter = sessions, dead_letter
        self._max_wait, self._renewal = max_wait_seconds, lock_renewal_seconds

    def open(self) -> Receiver | None:
        renewer = AutoLockRenewer(max_lock_renewal_duration=self._renewal) if self._renewal > 0 else None
        receiver = self._client.get_queue_receiver(
            self._queue,
            session_id=NEXT_AVAILABLE_SESSION if self._sessions else None,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER if self._dead_letter else None,
            max_wait_time=self._max_wait,
            auto_lock_renewer=renewer,
        )
        return _SdkReceiver(receiver, renewer)


class _Sender:
    def __init__(self, client: ServiceBusClient, queue: str) -> None:
        self._client, self._queue = client, queue

    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Send everything, starting a new batch whenever the current one is full."""
        with self._client.get_queue_sender(self._queue) as sender:
            batch = sender.create_message_batch()
            for outgoing in messages:
                message = ServiceBusMessage(
                    outgoing.body, message_id=outgoing.message_id, session_id=outgoing.session_id
                )
                try:
                    batch.add_message(message)
                except ValueError:  # the batch is full: send it and start the next
                    sender.send_messages(batch)
                    batch = sender.create_message_batch()
                    batch.add_message(message)
            if len(batch) > 0:
                sender.send_messages(batch)
