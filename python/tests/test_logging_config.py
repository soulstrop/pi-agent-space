"""Tests for structured JSON logging (pi-agent-space-wtw)."""

from __future__ import annotations

import json
import logging
import re

from pi_evaluator.logging_config import JsonFormatter


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
