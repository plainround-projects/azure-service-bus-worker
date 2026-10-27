"""`order-dlq`: read the dead-letter queue and fix, drop or keep each message (the replay tool)."""

import argparse
from collections.abc import Callable, Sequence

from order_worker.application.replay_dead_letters import Action, DeadLetterView, ReplayDeadLetters
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program

_CHOICES = {"f": Action.FIX, "d": Action.DROP, "k": Action.KEEP}


def ask(view: DeadLetterView) -> Action:
    """Show one dead letter and read the operator's choice."""
    print(
        f'{view.message_id}  reason={view.reason}  description="{view.description}"  '
        f"delivery_count={view.delivery_count}"
    )
    while True:
        choice = input("(f)ix, (d)rop, (k)eep? ").strip().lower()[:1]
        if choice in _CHOICES:
            return _CHOICES[choice]


def _always(action: Action) -> Callable[[DeadLetterView], Action]:
    """A decision function that returns the same action for every message (for scripts)."""
    return lambda _view: action


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-dlq", description=__doc__)
    parser.add_argument(
        "--action",
        choices=["ask", "fix", "drop", "keep"],
        default="ask",
        help="ask for each message (default), or apply one action to all (for scripts)",
    )
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        decide = ask if args.action == "ask" else _always(Action(args.action))
        with connect(settings) as messaging:
            report = ReplayDeadLetters(
                messaging.dead_letters(max_wait_seconds=min(settings.max_wait_seconds, 5.0)),
                messaging.sender(),
                decide,
            ).run()
        print(f"fixed={report.fixed} dropped={report.dropped} kept={report.kept}")
        return 0

    return run_program(run)


if __name__ == "__main__":
    raise SystemExit(main())
