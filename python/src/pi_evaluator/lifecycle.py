"""ADR 0007 lifecycle predicates shared between the orchestrator and adapters.

The model-error rule lives here so the orchestrator's outcome classifier
(:func:`pi_evaluator.trial_runner._classify_outcome`) and the
adapter-layer retry loop
(:class:`pi_evaluator.adapters.cli_subprocess_adapter.CliSubprocessAdapter`)
share a single source-of-kill definition. Phase 4.2's new lifecycle event
phases (``error_retry``, ``error_escalated``, ``boundary_violation``) will
extend this module rather than re-duplicating the rule.
"""

from __future__ import annotations

from .domain.types import RawTelemetry


def is_model_error(telemetry: RawTelemetry) -> bool:
    """ADR 0007 source-of-kill model-error rule.

    A non-zero subprocess exit, or an assistant ``message_end`` event whose
    ``stopReason`` is ``"error"``, both qualify as model-layer errors.
    """
    if telemetry.exit_code != 0:
        return True
    for event in telemetry.events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        if message.get("stopReason") == "error":
            return True
    return False
