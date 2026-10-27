"""A faithful-enough Service Bus for offline runs: peek-lock, lock expiry, delivery counts, sessions and dead-lettering.

It implements the same ports as the Azure adapters (`Inbox`, `Receiver`, `Delivery`, `Sender`), driven by a manual
clock, so the lesson's three failures reproduce deterministically in milliseconds. It is a teaching model, not an
emulator: see ARCHITECTURE.md, "Limits of the teaching build", for what it leaves out.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from order_worker.application.ports import Delivery, OutgoingMessage, Receiver
from order_worker.domain.errors import LockLostError

LOCK_LOST_TEXT = (
    "The lock supplied is invalid. Either the lock expired, or the message has already been removed from the queue."
)


class ManualClock:
    """Time that moves only when someone sleeps."""

    def __init__(self, start: float = 0.0) -> None:
        """Start at `start` seconds."""
        self._now = start

    def now(self) -> float:
        """Current virtual time in seconds."""
        return self._now

    def sleep(self, seconds: float) -> None:
        """Advance the clock; nothing really waits."""
        self._now += seconds


class _State(Enum):
    ACTIVE = "active"
    LOCKED = "locked"
    DEAD = "dead"


@dataclass(slots=True)
class _Message:
    order: int
    message_id: str
    body: bytes
    session_id: str | None
    delivery_count: int = 0
    state: _State = _State.ACTIVE
    lock_token: int = 0
    locked_until: float = 0.0
    received_at: float = 0.0
    dead_reason: str | None = None
    dead_description: str | None = None
    dlq_locked: bool = False


@dataclass(slots=True)
class BrokerCounts:
    """Messages by state."""

    active: int = 0
    locked: int = 0
    dead: int = 0


@dataclass(slots=True)
class SimulatedBroker:
    """One queue and its dead-letter sub-queue.

    `lock_duration` and `max_delivery_count` are the queue properties of the lesson (30 s, 10). `auto_renew_seconds`
    stands for the SDK's AutoLockRenewer: while above zero, a lock stays valid for that long after receipt however long
    processing takes. On a session queue a message is valid for as long as its session receiver is open.
    """

    clock: ManualClock
    sessions: bool = False
    lock_duration: float = 30.0
    max_delivery_count: int = 10
    auto_renew_seconds: float = 0.0
    max_wait_seconds: float = 10.0
    _messages: list[_Message] = field(default_factory=list)
    _session_holders: dict[str, int] = field(default_factory=dict)
    _next_token: int = 1
    _next_receiver: int = 1
    _max_delivery: int = 0

    # ----- Sender port
    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Append messages; a session queue refuses a message without a session id, as Service Bus does."""
        for outgoing in messages:
            if self.sessions and not outgoing.session_id:
                raise ValueError("the queue requires sessions: every message needs a session id")
            self._messages.append(
                _Message(len(self._messages), outgoing.message_id, outgoing.body.encode(), outgoing.session_id)
            )

    # ----- inboxes
    def inbox(self) -> "_Inbox":
        """Receivers for the main queue."""
        return _Inbox(self, dead_letter=False)

    def dead_letters(self) -> "_Inbox":
        """Receivers for the dead-letter sub-queue."""
        return _Inbox(self, dead_letter=True)

    # ----- inspection
    def counts(self) -> BrokerCounts:
        """How many messages are active, locked and dead-lettered right now."""
        self._expire_locks()
        counts = BrokerCounts()
        for message in self._messages:
            match message.state:
                case _State.ACTIVE:
                    counts.active += 1
                case _State.LOCKED:
                    counts.locked += 1
                case _State.DEAD:
                    counts.dead += 1
        return counts

    def dead_letter_reasons(self) -> list[tuple[str, str | None, str | None]]:
        """(message id, reason, description) of every dead letter."""
        return [(m.message_id, m.dead_reason, m.dead_description) for m in self._messages if m.state is _State.DEAD]

    def max_delivery_seen(self) -> int:
        """The highest delivery count any message ever reached, including messages already completed."""
        return self._max_delivery

    # ----- internals used by the receivers and deliveries
    def _lock_is_valid(self, message: _Message, token: int) -> bool:
        if message.state is not _State.LOCKED or message.lock_token != token:
            return False
        if self.sessions:
            return True
        now = self.clock.now()
        return now < message.locked_until or (
            self.auto_renew_seconds > 0 and now <= message.received_at + self.auto_renew_seconds
        )

    def _expire_locks(self) -> None:
        if self.sessions:
            return
        for message in self._messages:
            if message.state is _State.LOCKED and not self._lock_is_valid(message, message.lock_token):
                self._release(message)

    def _release(self, message: _Message) -> None:
        """Make a message available again, or dead-letter it when it was delivered the maximum number of times."""
        if message.delivery_count >= self.max_delivery_count:
            message.state = _State.DEAD
            message.dead_reason = "MaxDeliveryCountExceeded"
            message.dead_description = (
                f"Message could not be consumed after {self.max_delivery_count} delivery attempts."
            )
        else:
            message.state = _State.ACTIVE

    def _take(self, session_id: str | None) -> _Message | None:
        self._expire_locks()
        for message in self._messages:
            if message.state is _State.ACTIVE and (session_id is None or message.session_id == session_id):
                message.state = _State.LOCKED
                message.delivery_count += 1
                message.lock_token = self._next_token
                self._next_token += 1
                message.received_at = self.clock.now()
                self._max_delivery = max(self._max_delivery, message.delivery_count)
                message.locked_until = message.received_at + self.lock_duration
                return message
        return None

    def _next_free_session(self, receiver_id: int) -> str | None:
        self._expire_locks()
        for message in self._messages:
            if message.state is _State.ACTIVE and message.session_id is not None:
                holder = self._session_holders.get(message.session_id)
                if holder is None:
                    self._session_holders[message.session_id] = receiver_id
                    return message.session_id
        return None


class _Inbox:
    def __init__(self, broker: SimulatedBroker, *, dead_letter: bool) -> None:
        self._broker = broker
        self._dead_letter = dead_letter

    def open(self) -> Receiver | None:
        """A receiver; on a session queue it locks the next session with messages, or returns None after the wait."""
        broker = self._broker
        receiver_id = broker._next_receiver
        broker._next_receiver += 1
        if self._dead_letter:
            return _DeadLetterReceiver(broker)
        if not broker.sessions:
            return _Receiver(broker, None, receiver_id)
        session_id = broker._next_free_session(receiver_id)
        if session_id is None:
            return None
        return _Receiver(broker, session_id, receiver_id)


class _Receiver:
    def __init__(self, broker: SimulatedBroker, session_id: str | None, receiver_id: int) -> None:
        self._broker, self._session_id, self._receiver_id = broker, session_id, receiver_id

    def receive(self, max_wait_seconds: float) -> Delivery | None:
        message = self._broker._take(self._session_id)
        if message is None:
            self._broker.clock.sleep(max_wait_seconds)
            return None
        return _SimDelivery(self._broker, message, message.lock_token)

    def close(self) -> None:
        if self._session_id is not None and self._broker._session_holders.get(self._session_id) == self._receiver_id:
            del self._broker._session_holders[self._session_id]


class _DeadLetterReceiver:
    def __init__(self, broker: SimulatedBroker) -> None:
        self._broker = broker

    def receive(self, max_wait_seconds: float) -> Delivery | None:
        for message in self._broker._messages:
            if message.state is _State.DEAD and not message.dlq_locked:
                message.dlq_locked = True
                return _DeadLetterDelivery(self._broker, message)
        self._broker.clock.sleep(max_wait_seconds)
        return None

    def close(self) -> None:
        for message in self._broker._messages:
            message.dlq_locked = False


class _DeliveryView:
    """The read-only half of a delivery, shared by the main-queue and dead-letter deliveries."""

    def __init__(self, broker: SimulatedBroker, message: _Message) -> None:
        self._broker = broker
        self._message = message

    @property
    def message_id(self) -> str:
        return self._message.message_id

    @property
    def body(self) -> bytes:
        return self._message.body

    @property
    def delivery_count(self) -> int:
        return self._message.delivery_count

    @property
    def session_id(self) -> str | None:
        return self._message.session_id


class _SimDelivery(_DeliveryView):
    def __init__(self, broker: SimulatedBroker, message: _Message, token: int) -> None:
        super().__init__(broker, message)
        self._token = token

    @property
    def dead_letter_reason(self) -> str | None:
        return None

    @property
    def dead_letter_description(self) -> str | None:
        return None

    def _require_lock(self) -> None:
        if not self._broker._lock_is_valid(self._message, self._token):
            raise LockLostError(LOCK_LOST_TEXT)

    def complete(self) -> None:
        self._require_lock()
        self._broker._messages.remove(self._message)

    def abandon(self) -> None:
        self._require_lock()
        self._broker._release(self._message)

    def dead_letter(self, reason: str, description: str) -> None:
        self._require_lock()
        self._message.state = _State.DEAD
        self._message.dead_reason = reason
        self._message.dead_description = description


class _DeadLetterDelivery(_DeliveryView):
    @property
    def dead_letter_reason(self) -> str | None:
        return self._message.dead_reason

    @property
    def dead_letter_description(self) -> str | None:
        return self._message.dead_description

    def complete(self) -> None:
        self._broker._messages.remove(self._message)

    def abandon(self) -> None:
        self._message.dlq_locked = False

    def dead_letter(self, reason: str, description: str) -> None:
        raise NotImplementedError("a message in the dead-letter queue cannot be dead-lettered again")
