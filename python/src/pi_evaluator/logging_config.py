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
import os
import queue
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import QueueHandler, QueueListener
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

# MD3-A / commitment 1: run- and trial-scoped correlation IDs are carried in
# contextvars and stamped onto every record by ContextFilter, so no call site
# threads them through ``extra``. contextvars propagate correctly into
# asyncio.Tasks and, critically, are read at log time (in the originating
# context) — so attaching ContextFilter to the emitting handler keeps it correct
# under the QueueHandler isolation in commitment 5.
_run_id_var: ContextVar[str | None] = ContextVar("pi_evaluator_run_id", default=None)
_trial_id_var: ContextVar[str | None] = ContextVar(
    "pi_evaluator_trial_id", default=None
)


@contextmanager
def log_context(
    *, run_id: str | None = None, trial_id: str | None = None
) -> Iterator[None]:
    """Bind ``run_id`` and/or ``trial_id`` for the duration of the block.

    Set once at the run/trial boundary; ContextFilter stamps the bound values
    onto every record emitted within. Resets on exit (including on exception),
    so a trial's id does not leak past its trial.
    """
    tokens = []
    if run_id is not None:
        tokens.append((_run_id_var, _run_id_var.set(run_id)))
    if trial_id is not None:
        tokens.append((_trial_id_var, _trial_id_var.set(trial_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class ContextFilter(logging.Filter):
    """Stamp the currently-bound correlation IDs onto each record.

    Attached to handlers (not loggers) so it also covers records that propagate
    up from child loggers. Absent IDs are not stamped, keeping records emitted
    outside any run/trial context clean.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        run_id = _run_id_var.get()
        trial_id = _trial_id_var.get()
        if run_id is not None:
            record.run_id = run_id
        if trial_id is not None:
            record.trial_id = trial_id
        return True


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


# MD5-A: INFO by default; DEBUG (or any standard level name) via the LOG_LEVEL
# environment variable. Unrecognised names fall back to INFO rather than failing.
def _level_from_env() -> int:
    name = os.environ.get("LOG_LEVEL", "INFO").upper()
    return logging.getLevelNamesMapping().get(name, logging.INFO)


# Commitment 5: the listener owns the formatting/I/O handlers and runs in a
# background thread. Module-level so configure_logging is idempotent (a prior
# listener is stopped before a new one starts) and shutdown_logging can flush it.
_listener: QueueListener | None = None


def configure_logging(
    level: int | None = None,
    log_file: Path | None = None,
) -> None:
    """Route the pi_evaluator logger through a background QueueListener.

    A non-blocking ``QueueHandler`` on the root pushes records onto a queue; a
    ``QueueListener`` formats and writes them on a background thread (commitment
    5), so log I/O never delays trial timing. Writes JSON to stderr always, and
    to ``log_file`` additionally when provided (MD2-B, ``<base>/run.log``).

    ``level`` defaults to ``LOG_LEVEL`` from the environment (MD5-A), or ``INFO``.
    Call once at the application entry point; repeat calls reconfigure cleanly.
    """
    global _listener

    root = logging.getLogger("pi_evaluator")
    # Reconfigure cleanly: drain any prior listener and drop its queue handler,
    # so repeated calls (notably in tests) don't leak threads or duplicate output.
    shutdown_logging()
    for handler in list(root.handlers):
        if not isinstance(handler, logging.NullHandler):
            root.removeHandler(handler)

    root.setLevel(level if level is not None else _level_from_env())

    # Target handlers run inside the listener thread.
    targets: list[logging.Handler] = []
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    targets.append(stream_handler)

    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        targets.append(file_handler)

    # ContextFilter sits on the QueueHandler (the emitting side) so correlation
    # IDs are read in the caller's context, not the listener's worker thread.
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
    queue_handler = QueueHandler(log_queue)
    queue_handler.addFilter(ContextFilter())
    root.addHandler(queue_handler)

    _listener = QueueListener(log_queue, *targets, respect_handler_level=False)
    _listener.start()


def shutdown_logging() -> None:
    """Stop the background QueueListener, draining queued records first.

    Safe to call when nothing is configured. ``QueueListener.stop`` enqueues a
    sentinel and joins the worker thread, so all pending records are flushed to
    their handlers before this returns — making log output deterministic in
    tests and clean at process exit.
    """
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
