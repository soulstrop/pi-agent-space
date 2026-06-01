"""ADR 0007 lifecycle predicates and ADR 0011 outcome classifier.

The model-error rule lives here so the orchestrator's outcome classifier
(:func:`classify_outcome`) and the adapter-layer retry loop
(:class:`pi_evaluator.adapters.cli_subprocess_adapter.CliSubprocessAdapter`)
share a single source-of-kill definition.

**Scope.** This module owns two responsibilities:

1. A telemetry predicate (:func:`is_model_error`) that inspects a
   ``RawTelemetry`` to decide if it represents a model-layer failure.
   Per ADR 0007 A2, this is the *telemetry-classified* signal only.
2. The trial outcome classifier (:func:`classify_outcome`) that resolves
   the final ``Trial.outcome`` from the per-trial event stream plus
   per-problem telemetry, per ADR 0011.

The classifier reads the event stream first: any ``boundary_violation``
event wins, regardless of telemetry shape. *Watchdog-classified* outcomes
(``boundary_violation`` from the cost-cap watchdog in
``TrialRunner.run_trial``, future subprocess-timeout and bwrap sandbox-kill)
are owned by their killer in the form of *event emission* — the killer
emits the ``boundary_violation`` event with the cause in the payload, and
the classifier picks it up. The killer no longer assigns ``Trial.outcome``
directly.

Phase 4.2's new event phases (``error_retry``, ``error_escalated``) extend
this module — once they emit at telemetry-classification time, the
``per_problem_telemetry`` parameter can drop off and ``classify_outcome``
becomes pure projection over the event stream (Option C in ADR 0011).
"""

from __future__ import annotations

from .domain.telemetry import assistant_messages
from .domain.types import Outcome, RawTelemetry, TrialEvent


def is_model_error(telemetry: RawTelemetry) -> bool:
    """ADR 0007 source-of-kill model-error rule.

    A non-zero subprocess exit, or an assistant ``message_end`` event whose
    ``stopReason`` is ``"error"``, both qualify as model-layer errors.
    """
    if telemetry.exit_code != 0:
        return True
    return any(m.stop_reason == "error" for m in assistant_messages(telemetry.events))


def classify_outcome(
    events: list[TrialEvent],
    per_problem_telemetry: list[RawTelemetry],
) -> Outcome:
    """ADR 0011 event-stream-first outcome classifier.

    Resolves the final ``Trial.outcome`` from the per-trial event stream
    plus per-problem telemetry. The event stream wins: any
    ``boundary_violation`` event in ``events`` returns ``"boundary_violation"``
    regardless of telemetry. Otherwise, falls back to the telemetry
    predicate — any model error in any problem's telemetry escalates the
    trial to ``"error_escalated"``. With neither signal, ``"completed"``.
    """
    if any(e.phase == "boundary_violation" for e in events):
        return "boundary_violation"
    if any(is_model_error(t) for t in per_problem_telemetry):
        return "error_escalated"
    return "completed"
