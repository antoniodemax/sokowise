"""Structured JSON logging on the standard library (docs/ARCHITECTURE.md §9).

Every record carries the request ID when one is bound for the current task, so a
log line can be matched to the `request_id` in an error envelope.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import LogLevel

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else passed via `extra=` is emitted as a field.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "message",
    "asctime",
    "color_message",  # uvicorn attaches an ANSI-coloured duplicate of the message
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: LogLevel) -> None:
    """Route the root logger (and uvicorn's loggers) through the JSON formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn installs its own handlers; let its records flow to the root handler instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    # The access line is written by the request-ID middleware with request_id and duration.
    logging.getLogger("uvicorn.access").disabled = True
