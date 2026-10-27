"""Graceful shutdown: SIGTERM and SIGINT ask the loop to stop; the message in hand is finished first."""

import signal
import threading
from types import FrameType


class ShutdownFlag:
    """A flag set by SIGTERM or SIGINT. Pass `is_set` to the worker loop as `should_stop`."""

    def __init__(self) -> None:
        """Create an unset flag."""
        self._event = threading.Event()

    def install(self) -> None:
        """Route SIGTERM and SIGINT to this flag. A second signal exits at once."""
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def is_set(self) -> bool:
        """True once a stop was requested."""
        return self._event.is_set()

    def request(self) -> None:
        """Ask the loop to stop."""
        self._event.set()

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self._event.is_set():
            raise SystemExit(128 + signum)
        self._event.set()
