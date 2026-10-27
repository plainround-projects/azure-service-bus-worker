"""`order-worker`: receive order commands, write the ledger, settle each message after the commit."""

import argparse
import logging
from collections.abc import Sequence

from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.run_worker import RunWorker
from order_worker.domain.processing import Mode
from order_worker.infrastructure.clock import SystemClock
from order_worker.infrastructure.health_server import HealthServer
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.shutdown import ShutdownFlag
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, is_reachable, prepare_database
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program

LOGGER = logging.getLogger("order_worker.worker")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. SIGTERM or SIGINT finishes the message in hand, settles it, closes everything and exits 0."""
    parser = argparse.ArgumentParser(prog="order-worker", description=__doc__)
    parser.add_argument(
        "--until-idle", type=float, default=None, metavar="SECONDS", help="stop after this long without a message"
    )
    parser.add_argument("--max-messages", type=int, default=None)
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        prepare_database(settings.ledger_path, settings.sql_dir, with_migrations=settings.mode is Mode.IDEMPOTENT)
        shutdown = ShutdownFlag()
        shutdown.install()
        ledger = SqliteLedger(settings.ledger_path)
        health = None
        if settings.health_port is not None:
            health = HealthServer(
                settings.health_port, 4 * settings.max_wait_seconds, lambda: is_reachable(settings.ledger_path)
            )
            health.start()
        clock = SystemClock()
        try:
            with connect(settings) as messaging:
                inbox = messaging.inbox(
                    sessions=settings.use_sessions,
                    max_wait_seconds=settings.max_wait_seconds,
                    lock_renewal_seconds=settings.lock_renewal_seconds,
                )
                LOGGER.info(
                    "worker started",
                    extra={
                        "queue": settings.queue,
                        "sessions": settings.use_sessions,
                        "mode": settings.mode.value,
                        "lock_renewal_seconds": settings.lock_renewal_seconds,
                        "slow_every": settings.chaos.slow_every,
                    },
                )
                worker = RunWorker(
                    inbox,
                    HandleDelivery(ledger, clock, settings.mode, settings.chaos),
                    clock,
                    settings.max_wait_seconds,
                    heartbeat=health.beat if health else (lambda: None),
                )
                stats = worker.run(shutdown.is_set, args.until_idle, args.max_messages)
        finally:
            ledger.close()
            if health:
                health.stop()
        print(
            f"received={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} "
            f"dead_lettered={stats.dead_lettered} abandoned={stats.abandoned} lock_lost={stats.lock_lost}"
        )
        return 0

    return run_program(run)


if __name__ == "__main__":
    raise SystemExit(main())
