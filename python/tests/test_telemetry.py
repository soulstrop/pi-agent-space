"""Tests for domain.telemetry.assistant_message_ends."""

from __future__ import annotations

from pi_evaluator.domain.telemetry import assistant_message_ends


def test_empty_stream_returns_empty():
    assert assistant_message_ends([]) == []


def test_picks_assistant_message_ends_only():
    events = [
        {"type": "message_end", "message": {"role": "assistant", "x": 1}},
        {"type": "message_end", "message": {"role": "user", "x": 2}},
        {"type": "tool_call", "message": {"role": "assistant", "x": 3}},
        {"type": "message_end", "message": {"role": "assistant", "x": 4}},
    ]
    assert assistant_message_ends(events) == [
        {"role": "assistant", "x": 1},
        {"role": "assistant", "x": 4},
    ]


def test_tolerates_missing_or_null_message():
    events = [
        {"type": "message_end"},
        {"type": "message_end", "message": None},
        {"type": "message_end", "message": {"role": "assistant"}},
    ]
    assert assistant_message_ends(events) == [{"role": "assistant"}]
