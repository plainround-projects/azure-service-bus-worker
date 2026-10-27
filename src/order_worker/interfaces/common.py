"""Pieces shared by the command-line programs."""

import os
import sys
from collections.abc import Callable, Sequence

from order_worker.infrastructure.logging import configure_logging
from order_worker.infrastructure.settings import ConfigError, Settings


def run_program(main: Callable[[Settings], int], *, require_namespace: bool = True) -> int:
    """Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2."""
    try:
        settings = Settings.from_env(os.environ, require_namespace=require_namespace)
    except ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    return main(settings)


def parse_cents(text: str) -> int:
    """Turn '10000.0' (currency units) into cents."""
    whole, _, fraction = text.partition(".")
    return int(whole) * 100 + int((fraction + "00")[:2])


def argv_or_default(argv: Sequence[str] | None) -> Sequence[str]:
    """`sys.argv[1:]` when no explicit list is given."""
    return sys.argv[1:] if argv is None else argv
