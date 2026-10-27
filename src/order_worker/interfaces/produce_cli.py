"""`order-produce`: send the known set of commands (and the poison command) to the queue."""

import argparse
from collections.abc import Sequence

from order_worker.application.produce_orders import ProduceOrders
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-produce", description=__doc__)
    parser.add_argument("--customers", type=int, default=20)
    parser.add_argument("--per-customer", type=int, default=50)
    parser.add_argument("--no-poison", action="store_true", help="do not send the command that can never succeed")
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        with connect(settings) as messaging:
            sent = ProduceOrders(messaging.sender(), settings.use_sessions).run(
                args.customers, args.per_customer, include_poison=not args.no_poison
            )
        poison = "" if args.no_poison else " (the last one is the poison command)"
        print(f"sent {sent} messages to {settings.queue}{poison}")
        return 0

    return run_program(run)


if __name__ == "__main__":
    raise SystemExit(main())
