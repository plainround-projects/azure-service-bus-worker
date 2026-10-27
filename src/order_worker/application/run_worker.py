"""The receive loop: open a receiver, handle deliveries one at a time, stop gracefully."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from order_worker.application.handle_delivery import Effect, Handled, HandleDelivery
from order_worker.application.ports import Clock, Inbox

LOGGER = logging.getLogger("order_worker.loop")


@dataclass(slots=True)
class WorkerStats:
    """Counters for one run."""

    received: int = 0
    applied: int = 0
    skipped_duplicates: int = 0
    dead_lettered: int = 0
    abandoned: int = 0
    lock_lost: int = 0

    def add(self, handled: Handled) -> None:
        """Count one handled delivery."""
        self.received += 1
        match handled.effect:
            case Effect.APPLIED:
                self.applied += 1
            case Effect.SKIPPED_DUPLICATE:
                self.skipped_duplicates += 1
            case Effect.DEAD_LETTERED:
                self.dead_lettered += 1
            case Effect.ABANDONED:
                self.abandoned += 1
        if not handled.settled:
            self.lock_lost += 1


def _never() -> bool:
    return False


def _nothing() -> None:
    return None


@dataclass(slots=True)
class RunWorker:
    """Receive until told to stop, until idle for a while, or until a message budget is spent.

    `should_stop` is checked between messages, so the message in hand is always finished and settled before the worker
    exits (graceful shutdown). `heartbeat` is called on every pass so a health endpoint can tell a stuck loop from a
    quiet queue.
    """

    inbox: Inbox
    handler: HandleDelivery
    clock: Clock
    max_wait_seconds: float = 10.0
    heartbeat: Callable[[], None] = field(default=_nothing)

    def run(
        self,
        should_stop: Callable[[], bool] = _never,
        until_idle_seconds: float | None = None,
        max_messages: int | None = None,
    ) -> WorkerStats:
        """Run the loop and return the counters."""
        stats = WorkerStats()
        idle_since: float | None = None
        while not should_stop():
            self.heartbeat()
            received_before = stats.received
            self._drain(stats, should_stop, max_messages)
            if max_messages is not None and stats.received >= max_messages:
                break
            if stats.received > received_before:
                idle_since = None
                continue
            idle_since = self.clock.now() if idle_since is None else idle_since
            if until_idle_seconds is not None and self.clock.now() - idle_since >= until_idle_seconds:
                break
        LOGGER.info("worker stopped", extra={name: getattr(stats, name) for name in stats.__slots__})
        return stats

    def _drain(self, stats: WorkerStats, should_stop: Callable[[], bool], max_messages: int | None) -> None:
        receiver = self.inbox.open()
        if receiver is None:  # nothing to receive from right now (no session has messages): wait, do not spin
            self.clock.sleep(self.max_wait_seconds)
            return
        try:
            while not should_stop() and (max_messages is None or stats.received < max_messages):
                self.heartbeat()
                delivery = receiver.receive(self.max_wait_seconds)
                if delivery is None:
                    return
                stats.add(self.handler.handle(delivery))
        finally:
            receiver.close()
