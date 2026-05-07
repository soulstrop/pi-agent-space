"""Phase 1 stub scorer: returns fixed metrics regardless of telemetry."""

from __future__ import annotations

from ..domain.types import Metrics, RawTelemetry, SubjectiveScore, Trial
from ..ports.scoring_port import ScoringPort


class StubScorer(ScoringPort):
    """Returns the configured ``Metrics`` (and optional ``SubjectiveScore``)."""

    def __init__(
        self,
        metrics: Metrics | None = None,
        subjective: SubjectiveScore | None = None,
    ) -> None:
        self._metrics = metrics or Metrics(
            tokens_consumed=0,
            validation_pass_rate=0.0,
            quality_score=0.0,
        )
        self._subjective = subjective

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        return self._metrics

    def score_subjective(self, trial: Trial) -> SubjectiveScore | None:
        return self._subjective
