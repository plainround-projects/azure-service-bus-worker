"""How the worker treats a delivery, and what happened to it."""

from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    """`NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in
    the same transaction and skips repeats (step 3)."""

    NAIVE = "naive"
    IDEMPOTENT = "idempotent"


class Outcome(StrEnum):
    """What `HandleDelivery` did with one delivery."""

    APPLIED = "applied"
    DUPLICATE_SKIPPED = "duplicate-skipped"
    DEAD_LETTERED = "dead-lettered"
    LOCK_LOST = "lock-lost"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Chaos:
    """Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for
    `slow_seconds` before the commit. `slow_every == 0` turns it off."""

    slow_every: int = 0
    slow_seconds: float = 45.0

    def delays(self, seq: int, delivery_count: int) -> bool:
        """True when this delivery is the one to slow down. Only the first delivery sleeps, or the retry is slow too."""
        return self.slow_every > 0 and seq % self.slow_every == 0 and delivery_count == 1


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write."""

    applied: bool
    previous_seq: int
