"""Hand-written test doubles for the application ports."""

from collections.abc import Sequence

from order_worker.application.ports import OutgoingMessage
from order_worker.domain.commands import OrderCommand
from order_worker.domain.errors import LockLostError, TransientError, UnknownCustomerError
from order_worker.domain.processing import ApplyResult


class FakeDelivery:
    """A delivery that records how it was settled, in order, with the other fakes' events."""

    def __init__(
        self,
        body: bytes,
        message_id: str = "m-1",
        delivery_count: int = 1,
        session_id: str | None = None,
        events: list[str] | None = None,
        lock_lost: bool = False,
        reason: str | None = None,
        description: str | None = None,
    ) -> None:
        self.body = body
        self.message_id = message_id
        self.delivery_count = delivery_count
        self.session_id = session_id
        self.dead_letter_reason = reason
        self.dead_letter_description = description
        self.events = events if events is not None else []
        self.lock_lost = lock_lost
        self.settled: list[str] = []

    def _settle(self, verb: str) -> None:
        if self.lock_lost:
            raise LockLostError("lock lost")
        self.settled.append(verb)
        self.events.append(f"settle:{verb}")

    def complete(self) -> None:
        self._settle("complete")

    def abandon(self) -> None:
        self._settle("abandon")

    def dead_letter(self, reason: str, description: str) -> None:
        self._settle(f"dead-letter:{reason}:{description}")


class FakeLedger:
    """Records applies; can be told to raise, or to report a duplicate or a previous sequence."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.calls: list[tuple[str, OrderCommand, int, bool]] = []
        self.seen: set[str] = set()
        self.raise_error: Exception | None = None
        self.previous_seq = 0

    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        if self.raise_error is not None:
            raise self.raise_error
        self.calls.append((message_id, command, delivery_count, deduplicate))
        self.events.append(f"apply:{command.order_id}")
        if deduplicate and message_id in self.seen:
            return ApplyResult(applied=False, previous_seq=0)
        self.seen.add(message_id)
        return ApplyResult(applied=True, previous_seq=self.previous_seq)


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.time += seconds


class ScriptedReceiver:
    """Yields the scripted deliveries, then None; counts closes."""

    def __init__(
        self, deliveries: Sequence[FakeDelivery], clock: FakeClock | None = None, on_empty: float = 0.0
    ) -> None:
        self._deliveries = list(deliveries)
        self.closed = 0
        self._clock = clock
        self._on_empty = on_empty

    def receive(self, max_wait_seconds: float) -> FakeDelivery | None:
        if self._deliveries:
            return self._deliveries.pop(0)
        if self._clock is not None:
            self._clock.sleep(self._on_empty or max_wait_seconds)
        return None

    def close(self) -> None:
        self.closed += 1


class FakeInbox:
    """Opens the scripted receivers in turn; None when they run out."""

    def __init__(self, *receivers: ScriptedReceiver | None) -> None:
        self._receivers = list(receivers)
        self.opened = 0

    def open(self) -> ScriptedReceiver | None:
        self.opened += 1
        return self._receivers.pop(0) if self._receivers else None


class RecordingSender:
    def __init__(self, events: list[str] | None = None) -> None:
        self.sent: list[OutgoingMessage] = []
        self.events = events if events is not None else []

    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        self.sent.extend(messages)
        self.events.extend(f"send:{message.message_id}" for message in messages)


def transient() -> TransientError:
    return TransientError("busy")


def unknown_customer() -> UnknownCustomerError:
    return UnknownCustomerError("c99")
