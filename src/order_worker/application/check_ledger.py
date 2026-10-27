"""The final-state check: the lesson's "correct end state" as a function of the ledger."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from order_worker.application.ports import LedgerReader


@dataclass(frozen=True, slots=True)
class LedgerReport:
    """What the ledger holds, and every way it differs from the expected end state."""

    rows: int
    total_cents: int
    duplicate_orders: tuple[str, ...]
    out_of_order: tuple[str, ...]
    missing_sequences: tuple[str, ...]

    @property
    def total(self) -> float:
        """The total in currency units."""
        return self.total_cents / 100


@dataclass(frozen=True, slots=True)
class CheckLedger:
    """Compare the ledger with the expected end state of the producer's known set."""

    reader: LedgerReader

    def report(self, per_customer: int = 50) -> LedgerReport:
        """Summarize the ledger: duplicates, per-customer order violations and gaps in 1..`per_customer`."""
        rows = self.reader.rows()
        order_counts = Counter(row.order_id for row in rows)
        applied_seqs: dict[str, list[int]] = defaultdict(list)
        out_of_order: list[str] = []
        for row in rows:  # rows arrive in apply order
            seqs = applied_seqs[row.customer_id]
            if seqs and row.seq < max(seqs):
                out_of_order.append(f"{row.customer_id}: seq {row.seq} applied after seq {max(seqs)}")
            seqs.append(row.seq)
        missing = [
            f"{customer}: missing {sorted(set(range(1, per_customer + 1)) - set(seqs))}"
            for customer, seqs in sorted(applied_seqs.items())
            if set(range(1, per_customer + 1)) - set(seqs)
        ]
        return LedgerReport(
            rows=len(rows),
            total_cents=sum(row.amount_cents for row in rows),
            duplicate_orders=tuple(sorted(order for order, count in order_counts.items() if count > 1)),
            out_of_order=tuple(out_of_order),
            missing_sequences=tuple(missing),
        )

    def problems(self, expected_rows: int, expected_total_cents: int, per_customer: int = 50) -> list[str]:
        """The differences from the expected end state; an empty list means the ledger is exactly right."""
        report = self.report(per_customer)
        found: list[str] = []
        if report.rows != expected_rows:
            found.append(f"expected {expected_rows} rows, found {report.rows}")
        if report.total_cents != expected_total_cents:
            found.append(f"expected a total of {expected_total_cents / 100}, found {report.total}")
        found.extend(f"duplicate effect for order {order}" for order in report.duplicate_orders)
        found.extend(f"out of order: {line}" for line in report.out_of_order)
        found.extend(report.missing_sequences)
        return found
