"""The heart of the worker: what to do with one delivery."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from order_worker.application.ports import Clock, Delivery, Ledger
from order_worker.domain.commands import parse_command
from order_worker.domain.errors import LockLostError, PermanentError, TransientError
from order_worker.domain.ordering import is_next_in_sequence
from order_worker.domain.processing import Chaos, Mode

LOGGER = logging.getLogger("order_worker.handler")


class Effect(StrEnum):
    """What happened to the message."""

    APPLIED = "applied"
    SKIPPED_DUPLICATE = "skipped-duplicate"
    DEAD_LETTERED = "dead-lettered"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Handled:
    """The result of one delivery: its effect, and whether the message was settled.

    `settled` is False when the lock was lost before `complete` or `dead_letter`: the effect (a ledger row, say) stands,
    and the queue will deliver the message again.
    """

    effect: Effect
    settled: bool


@dataclass(frozen=True, slots=True)
class HandleDelivery:
    """Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing.

    A command that can never succeed is dead-lettered at once with a reason (retrying wastes work and delays the queue);
    a transient failure is abandoned; a lost lock is logged and left to redelivery, which `Mode.IDEMPOTENT` makes
    harmless.
    """

    ledger: Ledger
    clock: Clock
    mode: Mode = Mode.IDEMPOTENT
    chaos: Chaos = field(default_factory=Chaos)

    def handle(self, delivery: Delivery) -> Handled:
        """Process `delivery`; never raises for a failure the queue can handle."""
        try:
            command = parse_command(delivery.body)
            slow = self.chaos.delays(command.seq, delivery.delivery_count)
            LOGGER.info(
                "apply %s delivery_count=%d%s",
                command.order_id,
                delivery.delivery_count,
                f" (sleeping {self.chaos.slow_seconds:g} s)" if slow else "",
                extra={"order_id": command.order_id, "delivery_count": delivery.delivery_count},
            )
            if slow:
                self.clock.sleep(self.chaos.slow_seconds)
            result = self.ledger.apply(
                delivery.message_id, command, delivery.delivery_count, deduplicate=self.mode is Mode.IDEMPOTENT
            )
        except PermanentError as error:
            return self._dead_letter(delivery, error)
        except TransientError as error:
            LOGGER.warning("abandon %s: %s", delivery.message_id, error, extra={"order_id": delivery.message_id})
            return Handled(Effect.ABANDONED, self._settle(delivery.abandon, delivery.message_id, "abandon"))
        if (
            result.applied
            and result.previous_seq != command.seq
            and not is_next_in_sequence(result.previous_seq, command.seq)
        ):
            LOGGER.error(
                "out of order: customer %s applied seq %d after seq %d",
                command.customer_id,
                command.seq,
                result.previous_seq,
                extra={"customer_id": command.customer_id, "seq": command.seq, "previous_seq": result.previous_seq},
            )
        effect = Effect.APPLIED if result.applied else Effect.SKIPPED_DUPLICATE
        if not result.applied:
            LOGGER.info("skip %s: already processed", command.order_id, extra={"order_id": command.order_id})
        return Handled(effect, self._settle(delivery.complete, command.order_id, "complete"))

    def _dead_letter(self, delivery: Delivery, error: PermanentError) -> Handled:
        LOGGER.warning(
            "dead-letter %s: %s: %s",
            delivery.message_id,
            error.reason,
            error.description,
            extra={"order_id": delivery.message_id, "reason": error.reason},
        )
        settled = self._settle(
            lambda: delivery.dead_letter(error.reason, error.description), delivery.message_id, "dead-letter"
        )
        return Handled(Effect.DEAD_LETTERED, settled)

    @staticmethod
    def _settle(action: Callable[[], None], message_id: str, verb: str) -> bool:
        try:
            action()
        except LockLostError:
            LOGGER.warning(
                "%s failed for %s: the lock supplied is invalid",
                verb,
                message_id,
                extra={"order_id": message_id},
            )
            return False
        return True
