"""`order-check`: compare the ledger with the lesson's correct end state; exit 1 on any difference."""

import argparse
import sys
from collections.abc import Sequence

from order_worker.application.check_ledger import CheckLedger
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.sqlite_ledger import SqliteLedger
from order_worker.interfaces.common import argv_or_default, parse_cents, run_program


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-check", description=__doc__)
    parser.add_argument("--expected-rows", type=int, default=1000)
    parser.add_argument("--expected-total", default="10000.0", help="in currency units")
    parser.add_argument("--per-customer", type=int, default=50)
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        ledger = SqliteLedger(settings.ledger_path)
        try:
            checker = CheckLedger(ledger)
            report = checker.report(args.per_customer)
            problems = checker.problems(args.expected_rows, parse_cents(args.expected_total), args.per_customer)
        finally:
            ledger.close()
        print(f"{report.rows}|{report.total}")
        for problem in problems:
            print(f"MISMATCH: {problem}", file=sys.stderr)
        if not problems:
            print("OK: the ledger is exactly the expected end state")
        return 1 if problems else 0

    return run_program(run, require_namespace=False)


if __name__ == "__main__":
    raise SystemExit(main())
