"""Tests for domain.telemetry.assistant_messages."""

from __future__ import annotations

from pi_evaluator.domain.telemetry import AssistantMessage, assistant_messages


def test_empty_stream_returns_empty():
    assert assistant_messages([]) == []


def test_picks_assistant_message_ends_only():
    events = [
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "usage": {"totalTokens": 10, "cost": {"total": 0.5}},
            },
        },
        {
            "type": "message_end",
            "message": {"role": "user", "usage": {"totalTokens": 99}},
        },
        {"type": "tool_call", "message": {"role": "assistant"}},
        {
            "type": "message_end",
            "message": {"role": "assistant", "stopReason": "error"},
        },
    ]
    result = assistant_messages(events)
    assert result == [
        AssistantMessage(total_tokens=10, cost_total=0.5, stop_reason=None),
        AssistantMessage(total_tokens=0, cost_total=0.0, stop_reason="error"),
    ]


def test_tolerates_missing_or_null_subobjects():
    events = [
        {"type": "message_end"},
        {"type": "message_end", "message": None},
        {"type": "message_end", "message": {"role": "assistant", "usage": None}},
    ]
    assert assistant_messages(events) == [
        AssistantMessage(total_tokens=0, cost_total=0.0, stop_reason=None),
    ]
