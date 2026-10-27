"""One JSON object per log line on stdout, so Log Analytics can parse every field."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    """Render a record as JSON; fields passed through `extra=` become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the JSON line for `record`."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({key: value for key, value in vars(record).items() if key not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Send the root logger to stdout as JSON at `level`; calling it twice does not duplicate lines."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("azure").setLevel(logging.WARNING)  # the SDK logs every request header at INFO
