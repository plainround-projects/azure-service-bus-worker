"""The real clock."""

import time


class SystemClock:
    """Monotonic time and a real sleep."""

    def now(self) -> float:
        """Seconds on a monotonic scale."""
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        """Wait for real."""
        time.sleep(seconds)
