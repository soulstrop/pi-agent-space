"""Typed view over Pi's raw event stream (``RawTelemetry.events``).

Pi emits line-delimited JSON events as ``list[dict]``. The scorer needs
each assistant ``message_end`` event's token/cost usage; the lifecycle
classifier needs its ``stopReason``. Rather than have both layers dig
through the raw dict shape with ``.get()`` ladders, ``assistant_messages``
parses the relevant events into ``AssistantMessage`` once — the single
place that knows Pi's wire shape. Downstream code reads typed fields.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantMessage:
    """Typed projection of one assistant ``message_end`` event."""

    total_tokens: int
    cost_total: float
    stop_reason: str | None


def assistant_messages(events: list[dict]) -> list[AssistantMessage]:
    """Parse assistant ``message_end`` events into typed messages.

    Filters the raw stream to ``type == "message_end"`` events whose
    ``message.role`` is ``"assistant"`` and projects each onto the fields
    the scorer and lifecycle classifier consume, tolerating missing or
    null sub-objects in the raw payload.
    """
    messages: list[AssistantMessage] = []
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage") or {}
        cost = usage.get("cost") or {}
        messages.append(
            AssistantMessage(
                total_tokens=int(usage.get("totalTokens") or 0),
                cost_total=float(cost.get("total") or 0),
                stop_reason=message.get("stopReason"),
            )
        )
    return messages
