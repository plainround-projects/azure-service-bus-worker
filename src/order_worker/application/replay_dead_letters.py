"""The replay tool: read the dead-letter queue, then fix, drop or keep each message."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from order_worker.application.ports import Inbox, OutgoingMessage, Sender
from order_worker.domain.errors import PermanentError
from order_worker.domain.repair import repair_body

LOGGER = logging.getLogger("order_worker.replay")


class Action(StrEnum):
    """What to do with one dead letter."""

    FIX = "fix"
    DROP = "drop"
    KEEP = "keep"


@dataclass(frozen=True, slots=True)
class DeadLetterView:
    """What the operator sees for one dead letter."""

    message_id: str
    reason: str
    description: str
    delivery_count: int
    body: str
    session_id: str | None


@dataclass(slots=True)
class ReplayReport:
    """Counters for one replay run."""

    fixed: int = 0
    dropped: int = 0
    kept: int = 0


@dataclass(frozen=True, slots=True)
class ReplayDeadLetters:
    """Resubmit fixed messages to the main queue, then remove them from the dead-letter queue.

    The order is send first, then complete: a crash between the two leaves the message in the dead-letter queue and the
    queue holds its fixed copy, never neither. The copy keeps the original message id, so the worker's idempotency table
    makes a second run of this tool harmless.
    """

    dead_letters: Inbox
    sender: Sender
    decide: Callable[[DeadLetterView], Action]
    max_wait_seconds: float = 5.0

    def run(self) -> ReplayReport:
        """Go through the dead-letter queue once and return the counters."""
        report = ReplayReport()
        receiver = self.dead_letters.open()
        if receiver is None:
            return report
        seen: set[str] = set()
        try:
            while (delivery := receiver.receive(self.max_wait_seconds)) is not None:
                if delivery.message_id in seen:  # a kept message came back: the queue has been read once
                    delivery.abandon()
                    break
                seen.add(delivery.message_id)
                view = DeadLetterView(
                    delivery.message_id,
                    delivery.dead_letter_reason or "",
                    delivery.dead_letter_description or "",
                    delivery.delivery_count,
                    delivery.body.decode("utf-8", errors="replace"),
                    delivery.session_id,
                )
                action = self.decide(view)
                if action is Action.FIX and not self._resubmit(view):
                    action = Action.KEEP
                if action is Action.KEEP:
                    delivery.abandon()
                    report.kept += 1
                    continue
                delivery.complete()
                if action is Action.FIX:
                    report.fixed += 1
                else:
                    report.dropped += 1
        finally:
            receiver.close()
        return report

    def _resubmit(self, view: DeadLetterView) -> bool:
        try:
            fixed = repair_body(view.body, view.reason)
        except PermanentError as error:
            LOGGER.warning("cannot fix %s: %s", view.message_id, error, extra={"order_id": view.message_id})
            return False
        self.sender.send([OutgoingMessage(fixed, view.message_id, view.session_id)])
        LOGGER.info("resubmitted %s", view.message_id, extra={"order_id": view.message_id})
        return True
