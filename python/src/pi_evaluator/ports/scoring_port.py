"""ScoringPort: maps raw telemetry to objective metrics; ingests subjective scores."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ..domain.types import Metrics, RawTelemetry, SubjectiveScore, Trial


@runtime_checkable
class ScoringPort(Protocol):
    """Two methods, mirroring the computational/inferential split.

    ``score_objective`` is computational: deterministic, fast, fully
    observed at trial close. ``score_subjective`` is inferential: slow,
    async, may return ``None`` when no rating is yet available.
    """

    def score_objective(self, telemetry: RawTelemetry) -> Metrics: ...

    def score_subjective(self, trial: Trial) -> Optional[SubjectiveScore]: ...
