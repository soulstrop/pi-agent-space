"""Phase 5.1: subjective-score event schema.

These tests pin the shape of the ``subjective_score`` TrialEvent so that
Phase 5.2 (append + finalize) and Phase 5.4 (acceptance test) have a
stable contract. The append path itself (where relative to ``finalized``
the event sits) is resolved by ADR 0014 (S002) and is NOT exercised here.
"""

from __future__ import annotations

from dataclasses import asdict

from pi_evaluator.domain.events import subjective_score_event
from pi_evaluator.domain.types import SubjectiveScore


def _ss(
    score: float = 0.8,
    notes: str = "clear reasoning, well-structured output",
    scorer: str = "user:constans",
    timestamp: str = "2026-05-30T12:00:00Z",
) -> SubjectiveScore:
    return SubjectiveScore(score=score, notes=notes, scorer=scorer, timestamp=timestamp)


class TestSubjectiveScoreEventPhase:
    def test_phase_is_subjective_score(self):
        event = subjective_score_event(_ss())
        assert event.phase == "subjective_score"

    def test_timestamp_matches_scoring_timestamp(self):
        ss = _ss(timestamp="2026-05-30T09:15:00Z")
        event = subjective_score_event(ss)
        assert event.timestamp == "2026-05-30T09:15:00Z"


class TestSubjectiveScoreEventPayload:
    def test_payload_contains_score(self):
        event = subjective_score_event(_ss(score=0.9))
        assert event.payload["score"] == 0.9

    def test_payload_contains_notes(self):
        event = subjective_score_event(_ss(notes="verbose but correct"))
        assert event.payload["notes"] == "verbose but correct"

    def test_payload_contains_scorer(self):
        event = subjective_score_event(_ss(scorer="user:alice"))
        assert event.payload["scorer"] == "user:alice"

    def test_payload_keys_are_exactly_score_notes_scorer(self):
        """Payload has no extra keys and no missing keys.

        Timestamp is NOT in the payload — it lives at the event envelope
        level (TrialEvent.timestamp), following ADR 0012 metric_record
        conventions where fields that appear in the envelope are not
        duplicated in the payload.
        """
        event = subjective_score_event(_ss())
        assert set(event.payload.keys()) == {"score", "notes", "scorer"}

    def test_payload_does_not_contain_timestamp(self):
        event = subjective_score_event(_ss())
        assert "timestamp" not in event.payload

    def test_zero_score_is_valid(self):
        event = subjective_score_event(_ss(score=0.0))
        assert event.payload["score"] == 0.0

    def test_max_score_is_valid(self):
        event = subjective_score_event(_ss(score=1.0))
        assert event.payload["score"] == 1.0

    def test_empty_notes_is_valid(self):
        event = subjective_score_event(_ss(notes=""))
        assert event.payload["notes"] == ""


class TestSubjectiveScoreEventSerialisation:
    def test_asdict_round_trips_via_json_compatible_types(self):
        """Event serialises to a plain-dict structure (no non-JSON types)."""
        import json

        event = subjective_score_event(_ss())
        raw = asdict(event)
        # Raises if any field is not JSON-serialisable
        json.dumps(raw)

    def test_asdict_payload_matches_expected_shape(self):
        ss = _ss(score=0.75, notes="ok", scorer="user:bob", timestamp="2026-01-01T00:00:00Z")
        event = subjective_score_event(ss)
        raw = asdict(event)
        assert raw == {
            "phase": "subjective_score",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "score": 0.75,
                "notes": "ok",
                "scorer": "user:bob",
            },
        }
