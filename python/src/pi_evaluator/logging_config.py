"""Structured JSON logging for pi_evaluator.

Usage (at application entry point, not in library code):

    from pi_evaluator.logging_config import configure_logging
    configure_logging(level=logging.INFO, log_file=base_dir / "run.log")

Each log record is written as a single JSON line with four guaranteed fields
(``timestamp``, ``level``, ``logger``, ``message``) plus any structured fields
passed via the ``extra`` kwarg:

    logger.warning(
        "per-run cost cap warning",
        extra={"event": "per_run_cost_cap_warning", "cap_usd": 4.0},
    )

Library code must not call ``configure_logging``. Callers that do not
configure logging see nothing (NullHandler default).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

# Standard LogRecord attributes that are never treated as structured fields.
_SKIP: frozenset[str] = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "taskName", "thread", "threadName",
})

# Silence "No handlers could be found" for library consumers that don't
# call configure_logging.
logging.getLogger("pi_evaluator").addHandler(logging.NullHandler())


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        for key, val in vars(record).items():
            if key not in _SKIP and not key.startswith("_"):
                entry[key] = val
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, sort_keys=True)


def configure_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Attach JsonFormatter handlers to the pi_evaluator logger.

    Writes to stderr always. Writes to ``log_file`` additionally when
    provided — intended for run-level durability (e.g. ``<base>/run.log``).
    Call once at the application entry point.
    """
    root = logging.getLogger("pi_evaluator")
    root.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    root.addHandler(stream_handler)

    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
