"""Typed per-phase event payloads (ADR 0017).

``Event.payload`` stays a ``dict`` on the ``Event`` dataclass and on disk; this
module is a typed *build/parse layer* over it, not a change to ``Event``.
Producers construct the per-phase dataclass and :func:`to_payload` it into
``Event.payload``; the structural consumer (``capability_profile``) calls
:func:`parse` once and reads typed fields. The phase string binds producer and
consumer to the same field names, closing the stringly-typed coupling flagged by
``pi-agent-space-3kz``. This mirrors the typed-view pattern already used for the
``RawTelemetry`` half of that issue (``domain/telemetry.py``).

Reads go through the tolerant seam (ADR 0019 D4): an event written by a newer
minor schema parses by dropping unknown payload keys (logged at info); additive
fields fall back to their dataclass defaults (D3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .tolerant_read import tolerant
from .types import Event


@dataclass(frozen=True)
class Configured:
    package_model: str


@dataclass(frozen=True)
class EvalRecord:
    problem_id: str
    difficulty: int
    exit_code: int


@dataclass(frozen=True)
class MetricRecord:
    problem_id: str
    metric_name: str
    value: float
    n_samples: int = 1


@dataclass(frozen=True)
class CostCapWarning:
    scope: str
    cap_usd: float
    cumulative_cost_dollars: float
    fraction: float


@dataclass(frozen=True)
class BoundaryViolation:
    """Both boundary-violation shapes (timeout vs. cost cap) in one model,
    discriminated by ``reason``; the shape-specific fields are optional."""

    reason: str
    problem_id: str | None = None
    timeout_seconds: float | None = None
    cap_usd: float | None = None
    cumulative_cost_dollars: float | None = None


@dataclass(frozen=True)
class Finalized:
    tokens_consumed: int
    cost_dollars: float
    validation_pass_rate: float
    quality_score: float
    outcome: str


EventPayload = (
    Configured
    | EvalRecord
    | MetricRecord
    | CostCapWarning
    | BoundaryViolation
    | Finalized
)

# Trial-stream phases that carry a typed payload. Run-stream phases (ADR 0013)
# share the Event shape but are not modelled here; parse() returns None for them.
_PHASE_MODELS: dict[str, type[EventPayload]] = {
    "configured": Configured,
    "eval": EvalRecord,
    "metric_record": MetricRecord,
    "cost_cap_warning": CostCapWarning,
    "boundary_violation": BoundaryViolation,
    "finalized": Finalized,
}


def parse(event: Event) -> EventPayload | None:
    """Parse an event's payload into its typed per-phase model.

    Returns ``None`` when the phase has no typed model (e.g. run-stream phases)
    *or* when the payload lacks a field the model requires — a partial or
    malformed event is treated as un-projectable rather than fatal, consistent
    with the defensive projection ``capability_profile`` performed before typing
    and with ADR 0017's no-hard-validation stance. Unknown payload keys are
    dropped and logged via the tolerant reader (ADR 0019 D4).
    """
    cls = _PHASE_MODELS.get(event.phase)
    if cls is None:
        return None
    try:
        return tolerant(cls, event.payload, where=f"event:{event.phase}")
    except TypeError:
        return None


def to_payload(obj: EventPayload) -> dict[str, Any]:
    """Serialize a typed payload to the on-disk dict.

    Drops ``None``-valued optional fields so the JSON matches the hand-built
    payloads byte-for-byte (no new null keys); absent fields are restored to
    their defaults on the way back through :func:`parse`.
    """
    return {k: v for k, v in asdict(obj).items() if v is not None}
