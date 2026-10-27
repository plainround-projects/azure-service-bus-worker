"""`order-simulate`: the lesson's three failures on a simulated Service Bus, offline, in seconds."""

import argparse
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from order_worker.domain.processing import Mode
from order_worker.infrastructure.scenarios import (
    PoisonResult,
    ScenarioResult,
    run_duplicates,
    run_ordering,
    run_poison_and_replay,
)
from order_worker.infrastructure.settings import REPOSITORY_SQL
from order_worker.interfaces.common import argv_or_default


class _Highlights(logging.Handler):
    """Print only the log lines that tell the story, not 1,000 `apply` lines."""

    _INTERESTING = ("sleeping", "failed", "dead-letter", "out of order", "skip ")
    _SHOWN = 6

    def __init__(self) -> None:
        super().__init__()
        self._matching = 0

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if not any(word in message for word in self._INTERESTING):
            return
        self._matching += 1
        if self._matching <= self._SHOWN:
            print(f"  log  {message}")

    def summary(self) -> None:
        """Say how many matching lines were not printed, then start counting again."""
        if self._matching > self._SHOWN:
            print(f"  log  ... {self._matching - self._SHOWN} more lines like these")
        self._matching = 0


def _show(result: ScenarioResult) -> None:
    stats, report = result.stats, result.report
    print(
        f"  handled={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} "
        f"dead_lettered={stats.dead_lettered} lock_lost={stats.lock_lost}"
    )
    print(
        f"  ledger: {report.rows}|{report.total}   highest delivery count: {result.max_delivery_count}   "
        f"dead letters: {result.broker.dead}"
    )
    for problem in result.problems[:5]:
        print(f"  MISMATCH: {problem}")
    if len(result.problems) > 5:
        print(f"  ... and {len(result.problems) - 5} more")
    if not result.problems:
        print("  OK: exactly the expected end state")


def _show_poison(result: PoisonResult) -> None:
    for message_id, reason, description in result.dead_letters_before:
        print(f'  dead letter: {message_id}  reason={reason}  description="{description}"')
    print(f"  ledger rows while the poison waits: {result.ledger_rows_before} (the other commands kept flowing)")
    print(f"  replay: fixed={result.replay.fixed}; a second replay finds fixed={result.second_replay.fixed}")
    print(f"  rows for o-bad after the replay: {result.o_bad_rows}")
    _show(result.after)


def _exit_code(dirty: bool, expect: str | None) -> int:
    """0 unless `--expect` was given and the outcome differs from it."""
    if expect is None:
        return 0
    return 0 if dirty == (expect == "dirty") else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-simulate", description=__doc__)
    parser.add_argument(
        "--expect",
        choices=["clean", "dirty"],
        default=None,
        help="exit 1 unless the final ledger is exactly right (clean) or visibly wrong (dirty); default: always exit 0",
    )
    sub = parser.add_subparsers(dest="scenario", required=True)
    duplicates = sub.add_parser("duplicates", help="steps 1 to 3: a 30 s lock and a 45 s command")
    duplicates.add_argument("--mode", choices=[m.value for m in Mode], default="naive")
    duplicates.add_argument("--renew", type=int, default=0, metavar="SECONDS", help="auto lock renewal, 0 = off")
    duplicates.add_argument(
        "--slow-every",
        type=int,
        default=10,
        metavar="N",
        help="slow the first delivery of every Nth seq; 0 = never (step 1)",
    )
    ordering = sub.add_parser("ordering", help="step 4: four workers, one stalls")
    ordering.add_argument("--sessions", action="store_true")
    sub.add_parser("poison", help="steps 5 and 6: dead-letter, then fix and replay")
    args = parser.parse_args(argv_or_default(argv))

    highlights = _Highlights()
    logging.getLogger().handlers[:] = [highlights]
    logging.getLogger().setLevel(logging.INFO)
    sql_dir = Path(os.environ.get("SQL_DIR", str(REPOSITORY_SQL)))  # the image sets SQL_DIR; a checkout uses ./sql
    with tempfile.TemporaryDirectory() as folder:
        database = Path(folder) / "orders.db"
        match args.scenario:
            case "duplicates":
                slow = f"every {args.slow_every}th seq takes 45 s" if args.slow_every else "no slow commands"
                print(f"duplicates: mode={args.mode} lock renewal={args.renew}s, 30 s lock, {slow}")
                result = run_duplicates(
                    database,
                    sql_dir,
                    mode=Mode(args.mode),
                    lock_renewal_seconds=args.renew,
                    slow_every=args.slow_every,
                )
                highlights.summary()
                _show(result)
                return _exit_code(bool(result.problems), args.expect)
            case "ordering":
                print(f"ordering: 4 workers, sessions={'on' if args.sessions else 'off'}, worker 0 stalls on o-c01-010")
                result = run_ordering(database, sql_dir, sessions=args.sessions)
                highlights.summary()
                _show(result)
                return _exit_code(bool(result.problems), args.expect)
            case _:
                print("poison: one command with amount 'abc', then the replay tool")
                poison = run_poison_and_replay(database, sql_dir)
                highlights.summary()
                _show_poison(poison)
                return _exit_code(bool(poison.after.problems) or poison.o_bad_rows != 1, args.expect)


if __name__ == "__main__":
    raise SystemExit(main())
