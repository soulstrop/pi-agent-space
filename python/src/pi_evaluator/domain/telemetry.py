"""Helpers for reading Pi's raw event stream (``RawTelemetry.events``).

Pi emits line-delimited JSON events; the scorer and the lifecycle
classifier both need the assistant ``message_end`` events (the scorer
sums their ``usage``; the classifier inspects their ``stopReason``).
Centralizing the event-shape knowledge here keeps that raw schema in one
place rather than duplicated across the scoring and lifecycle layers.
"""

from __future__ import annotations


def assistant_message_ends(events: list[dict]) -> list[dict]:
    """Return the ``message`` dicts of assistant ``message_end`` events.

    Filters the raw event stream to ``type == "message_end"`` events whose
    ``message.role`` is ``"assistant"``, returning each event's ``message``
    payload (never ``None``).
    """
    messages: list[dict] = []
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") == "assistant":
            messages.append(message)
    return messages
