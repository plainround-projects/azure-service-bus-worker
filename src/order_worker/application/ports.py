"""What the use cases need from the outside world."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from order_worker.domain.commands import OrderCommand
from order_worker.domain.processing import ApplyResult


class Delivery(Protocol):
    """One received message under a lock (Service Bus peek-lock). Exactly one of the three settle methods ends it."""

    @property
    def message_id(self) -> str:
        """The producer's message id; the idempotency key."""
        ...

    @property
    def body(self) -> bytes:
        """The message body."""
        ...

    @property
    def delivery_count(self) -> int:
        """How many times the queue has delivered this message, this delivery included (1 on the first)."""
        ...

    @property
    def session_id(self) -> str | None:
        """The session id, or None on a queue without sessions."""
        ...

    @property
    def dead_letter_reason(self) -> str | None:
        """On a dead letter: the reason it was dead-lettered with."""
        ...

    @property
    def dead_letter_description(self) -> str | None:
        """On a dead letter: the error description."""
        ...

    def complete(self) -> None:
        """Remove the message from the queue. Raises `LockLostError` when the lock is no longer valid."""
        ...

    def abandon(self) -> None:
        """Release the lock so the message is delivered again."""
        ...

    def dead_letter(self, reason: str, description: str) -> None:
        """Move the message to the dead-letter queue at once, with a reason and a description."""
        ...


class Receiver(Protocol):
    """Receives deliveries from one queue or one session."""

    def receive(self, max_wait_seconds: float) -> Delivery | None:
        """Wait up to `max_wait_seconds` for a message; None when there is none."""
        ...

    def close(self) -> None:
        """Release the receiver (and the session lock, if it holds one)."""
        ...


class Inbox(Protocol):
    """Opens receivers on a queue (or on its dead-letter sub-queue)."""

    def open(self) -> Receiver | None:
        """A receiver, or None when nothing can be received from right now; the caller waits before it asks again."""
        ...


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A message to send. The message id is the idempotency key; the session id is the customer on a session queue."""

    body: str
    message_id: str
    session_id: str | None = None


class Sender(Protocol):
    """Sends messages to the main queue."""

    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Send all of `messages`, batching as the transport requires."""
        ...


class Ledger(Protocol):
    """The small database the worker writes results to."""

    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        """Write the command's row in one transaction.

        With `deduplicate`, record `message_id` in the same transaction and write nothing for a message seen before.
        Raises `UnknownCustomerError` (permanent) or `TransientError` (retry).
        """
        ...


@dataclass(frozen=True, slots=True)
class OrderRow:
    """One ledger row, in the order it was applied."""

    apply_order: int
    order_id: str
    customer_id: str
    seq: int
    amount_cents: int
    delivery_count: int


class LedgerReader(Protocol):
    """Read access to the ledger, for the final-state check."""

    def rows(self) -> Sequence[OrderRow]:
        """Every row, in apply order."""
        ...


class Clock(Protocol):
    """Time, injected so tests and the simulation are deterministic."""

    def now(self) -> float:
        """Seconds on a monotonic scale."""
        ...

    def sleep(self, seconds: float) -> None:
        """Wait."""
        ...
