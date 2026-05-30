"""Event-construction helpers for the trial event stream.

Each public function in this module builds a ``TrialEvent`` for a
specific phase. The helpers centralise the mapping from domain types to
event payload fields so call sites don't inline the mapping logic.

Phase 5.1: subjective_score_event is the first entry; objective-phase
helpers live in trial_runner._metric_records and TrialRunner._emit for now.
"""

from __future__ import annotations

from ..domain.types import SubjectiveScore, TrialEvent


def subjective_score_event(ss: SubjectiveScore) -> TrialEvent:
    """Build a ``subjective_score`` TrialEvent from a SubjectiveScore.

    The event's ``timestamp`` is the scoring timestamp from ``ss``.
    Payload carries ``score``, ``notes``, and ``scorer`` — the fields
    a human annotator supplies. ``timestamp`` is not repeated in the
    payload because it already lives at the event envelope level, following
    the convention established by ``metric_record`` events (ADR 0012).

    Phase 5.2 will append this event to ``events.jsonl``.  Where it sits
    relative to ``finalized`` is resolved by ADR 0014 (S002).
    """
    return TrialEvent(
        phase="subjective_score",
        timestamp=ss.timestamp,
        payload={
            "score": ss.score,
            "notes": ss.notes,
            "scorer": ss.scorer,
        },
    )
