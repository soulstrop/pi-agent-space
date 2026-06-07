"""Tests for structured JSON logging (pi-agent-space-wtw)."""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import QueueHandler

import pytest

from pi_evaluator.logging_config import (
    ContextFilter,
    JsonFormatter,
    configure_logging,
    log_context,
    shutdown_logging,
)


def _format(
    message: str = "test message",
    level: int = logging.WARNING,
    name: str = "pi_evaluator.test",
    extra: dict | None = None,
) -> dict:
    """Emit a log record through JsonFormatter and parse the result."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    formatter = JsonFormatter()
    raw = formatter.format(record)
    return json.loads(raw)


class TestJsonFormatterGuaranteedFields:
    def test_timestamp_present(self):
        assert "timestamp" in _format()

    def test_timestamp_is_iso8601_utc(self):
        ts = _format()["timestamp"]
        # e.g. "2026-05-30T12:00:00+00:00"
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)
        assert ts.endswith("+00:00")

    def test_level_present(self):
        assert _format(level=logging.WARNING)["level"] == "WARNING"

    def test_level_info(self):
        assert _format(level=logging.INFO)["level"] == "INFO"

    def test_logger_present(self):
        assert _format(name="pi_evaluator.optimizer_driver")["logger"] == \
            "pi_evaluator.optimizer_driver"

    def test_message_present(self):
        assert _format(message="hello")["message"] == "hello"


class TestJsonFormatterStructuredFields:
    def test_extra_fields_appear_in_output(self):
        result = _format(extra={"event": "per_run_cost_cap_warning", "cap_usd": 4.0})
        assert result["event"] == "per_run_cost_cap_warning"
        assert result["cap_usd"] == 4.0

    def test_multiple_extra_fields(self):
        result = _format(extra={
            "event": "per_run_cost_cap_warning",
            "cumulative_cost_dollars": 3.2,
            "cap_usd": 4.0,
            "threshold_fraction": 0.8,
        })
        assert result["cumulative_cost_dollars"] == 3.2
        assert result["threshold_fraction"] == 0.8

    def test_standard_attrs_not_duplicated(self):
        result = _format()
        # These are surfaced under their canonical names, not as raw record attrs
        assert "levelno" not in result
        assert "lineno" not in result
        assert "msg" not in result
        assert "args" not in result

    def test_private_attrs_excluded(self):
        result = _format()
        assert all(not k.startswith("_") for k in result)


class TestJsonFormatterOutput:
    def test_output_is_valid_json(self):
        raw = JsonFormatter().format(
            logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
        )
        json.loads(raw)  # raises if invalid

    def test_output_is_single_line(self):
        raw = JsonFormatter().format(
            logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
        )
        assert "\n" not in raw

    def test_non_serialisable_extra_becomes_string(self):
        result = _format(extra={"obj": object()})
        assert isinstance(result["obj"], str)


def _record() -> logging.LogRecord:
    return logging.LogRecord("pi_evaluator.t", logging.INFO, "p", 1, "m", (), None)


class TestContextBinding:
    """MD3-A / commitment 1: run_id + trial_id stamped via contextvars."""

    def test_filter_stamps_run_and_trial_inside_context(self):
        f = ContextFilter()
        with log_context(run_id="r1", trial_id="t1"):
            rec = _record()
            assert f.filter(rec) is True
            assert getattr(rec, "run_id") == "r1"
            assert getattr(rec, "trial_id") == "t1"

    def test_filter_stamps_nothing_outside_context(self):
        f = ContextFilter()
        rec = _record()
        f.filter(rec)
        assert not hasattr(rec, "run_id")
        assert not hasattr(rec, "trial_id")

    def test_context_resets_on_exit(self):
        f = ContextFilter()
        with log_context(run_id="r1"):
            pass
        rec = _record()
        f.filter(rec)
        assert not hasattr(rec, "run_id")

    def test_trial_context_nests_within_run(self):
        f = ContextFilter()
        with log_context(run_id="r1"):
            with log_context(trial_id="t1"):
                inner = _record()
                f.filter(inner)
                assert getattr(inner, "run_id") == "r1"
                assert getattr(inner, "trial_id") == "t1"
            after = _record()
            f.filter(after)
            assert getattr(after, "run_id") == "r1"
            assert not hasattr(after, "trial_id")

    def test_stamped_fields_reach_json_output(self):
        f = ContextFilter()
        with log_context(run_id="r9", trial_id="t9"):
            rec = _record()
            f.filter(rec)
        result = json.loads(JsonFormatter().format(rec))
        assert result["run_id"] == "r9"
        assert result["trial_id"] == "t9"


@pytest.fixture
def _logging_teardown():
    """Restore the pi_evaluator logger to its import-time state after each test."""
    yield
    shutdown_logging()
    root = logging.getLogger("pi_evaluator")
    for h in list(root.handlers):
        if not isinstance(h, logging.NullHandler):
            root.removeHandler(h)


class TestConfigureLogging:
    """Commitment 5 (QueueHandler isolation) + MD5-A (LOG_LEVEL env)."""

    def test_root_routes_through_queue_handler(self, _logging_teardown):
        configure_logging()
        root = logging.getLogger("pi_evaluator")
        non_null = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert len(non_null) == 1
        assert isinstance(non_null[0], QueueHandler)

    def test_context_filter_on_queue_handler(self, _logging_teardown):
        configure_logging()
        root = logging.getLogger("pi_evaluator")
        qh = next(h for h in root.handlers if isinstance(h, QueueHandler))
        assert any(isinstance(f, ContextFilter) for f in qh.filters)

    def test_log_level_env_default(self, monkeypatch, _logging_teardown):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        configure_logging()
        assert logging.getLogger("pi_evaluator").level == logging.DEBUG

    def test_default_level_is_info(self, monkeypatch, _logging_teardown):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        configure_logging()
        assert logging.getLogger("pi_evaluator").level == logging.INFO

    def test_explicit_level_overrides_env(self, monkeypatch, _logging_teardown):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        configure_logging(level=logging.WARNING)
        assert logging.getLogger("pi_evaluator").level == logging.WARNING

    def test_unknown_log_level_falls_back_to_info(self, monkeypatch, _logging_teardown):
        monkeypatch.setenv("LOG_LEVEL", "NONSENSE")
        configure_logging()
        assert logging.getLogger("pi_evaluator").level == logging.INFO

    def test_idempotent_no_handler_leak(self, _logging_teardown):
        configure_logging()
        configure_logging()
        root = logging.getLogger("pi_evaluator")
        non_null = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert len(non_null) == 1

    def test_records_reach_file_with_context_ids(self, tmp_path, _logging_teardown):
        log_file = tmp_path / "run.log"
        configure_logging(log_file=log_file)
        logger = logging.getLogger("pi_evaluator.test")
        with log_context(run_id="rX", trial_id="tX"):
            logger.info("hello", extra={"event": "probe"})
        # stop() drains the queue and joins the listener thread (flush).
        shutdown_logging()
        lines = [
            json.loads(ln) for ln in log_file.read_text().splitlines() if ln.strip()
        ]
        probe = next(r for r in lines if r.get("event") == "probe")
        assert probe["run_id"] == "rX"
        assert probe["trial_id"] == "tX"
        assert probe["message"] == "hello"
