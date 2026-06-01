"""Real ScoringPort: derive Metrics from RawTelemetry produced by the Pi adapter."""

from __future__ import annotations

from ..domain.telemetry import assistant_messages
from ..domain.types import (
    Metrics,
    RawTelemetry,
    SubjectiveScore,
    Trial,
)
from ..ports.scoring_port import ScoringPort


class SyntheticSuiteScorer(ScoringPort):
    """v1 objective scorer.

    - ``tokens_consumed``: sum of ``usage.totalTokens`` over every
      assistant ``message_end`` event in the telemetry stream.
    - ``cost_dollars``: sum of ``usage.cost.total`` over the same
      events. Per ADR 0005, tokens and dollars are tracked as
      independent axes — token-cheap models can be dollar-expensive
      across providers.
    - ``validation_pass_rate``: fraction of ValidationResults marked
      ``passed``; 0.0 when there are no validation results (no signal
      of success).
    - ``quality_score``: ``validation_pass_rate * 1.0`` — intentionally
      minimal in v1; weights and additional axes land in their own ADR.

    Subjective scoring returns ``None``; subjective signal is async
    and arrives via the Phase 5 path, not the synchronous trial loop.
    """

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        messages = assistant_messages(telemetry.events)
        pass_rate = _validation_pass_rate(telemetry)
        return Metrics(
            tokens_consumed=sum(m.total_tokens for m in messages),
            cost_dollars=sum(m.cost_total for m in messages),
            validation_pass_rate=pass_rate,
            quality_score=pass_rate * 1.0,
        )

    def score_subjective(self, trial: Trial) -> SubjectiveScore | None:
        return None


def _validation_pass_rate(telemetry: RawTelemetry) -> float:
    results = telemetry.validation_results
    if not results:
        return 0.0
    return sum(1 for r in results if r.passed) / len(results)
