"""Real ScoringPort: derive Metrics from RawTelemetry produced by the Pi adapter."""

from __future__ import annotations

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
    - ``validation_pass_rate``: fraction of ValidationResults marked
      ``passed``; 0.0 when there are no validation results (no signal
      of success).
    - ``quality_score``: ``validation_pass_rate * 1.0`` — intentionally
      minimal in v1; weights and additional axes land in their own ADR.

    Subjective scoring returns ``None``; subjective signal is async
    and arrives via the Phase 5 path, not the synchronous trial loop.
    """

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        return Metrics(
            tokens_consumed=_sum_assistant_tokens(telemetry.events),
            validation_pass_rate=_validation_pass_rate(telemetry),
            quality_score=_validation_pass_rate(telemetry) * 1.0,
        )

    def score_subjective(self, trial: Trial) -> SubjectiveScore | None:
        return None


def _sum_assistant_tokens(events: list[dict]) -> int:
    total = 0
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage") or {}
        total += int(usage.get("totalTokens", 0))
    return total


def _validation_pass_rate(telemetry: RawTelemetry) -> float:
    results = telemetry.validation_results
    if not results:
        return 0.0
    return sum(1 for r in results if r.passed) / len(results)
