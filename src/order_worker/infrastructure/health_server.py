"""A tiny HTTP health endpoint, because Container Apps probes speak HTTP, not shell commands.

`/live` answers 200 while the receive loop has made progress recently (a loop stuck in a hung call fails it and the
platform restarts the replica). `/ready` also checks that the ledger answers.
"""

import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthServer:
    """Serves `/live` and `/ready` on a background thread."""

    def __init__(
        self,
        port: int,
        stale_after_seconds: float,
        ledger_ok: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind to `port` on all interfaces; the loop must call `beat` at least every `stale_after_seconds`.

        `monotonic` is injectable so tests control time.
        """
        self._monotonic = monotonic
        self._last_beat = monotonic()
        self._stale_after = stale_after_seconds
        self._ledger_ok = ledger_ok
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                healthy = server.alive() and (self.path != "/ready" or server._ledger_ok())
                known = self.path in ("/live", "/ready")
                self.send_response(200 if healthy and known else 404 if not known else 503)
                self.end_headers()
                self.wfile.write(b"ok\n" if healthy and known else b"unhealthy\n")

            def log_message(self, format: str, *args: object) -> None:
                return None  # the worker's own logs are the record

        self._httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="health", daemon=True)

    @property
    def port(self) -> int:
        """The bound port (useful when started with port 0)."""
        return int(self._httpd.server_address[1])

    def beat(self) -> None:
        """Record that the receive loop is making progress."""
        self._last_beat = self._monotonic()

    def alive(self) -> bool:
        """True when the loop beat within the stale window."""
        return self._monotonic() - self._last_beat < self._stale_after

    def start(self) -> None:
        """Start serving."""
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        self._httpd.shutdown()
        self._httpd.server_close()
