"""Trial orchestrator: composes the four Phase 1 ports into a pipeline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    Trial,
    TrialEvent,
    VersionVector,
)
from .ports.agent_harness_port import AgentHarnessPort
from .ports.eval_suite_source_port import EvalSuiteSourcePort
from .ports.persistence_port import PersistencePort
from .ports.scoring_port import ScoringPort


def _default_clock() -> str:
    return datetime.now(UTC).isoformat()


class TrialRunner:
    """Run one trial end-to-end against a graduated problem suite.

    Per the trial event-stream model (ADR 0003), a trial moves through:
    configured → (eval, scored_objective)* → finalized. Subjective
    scoring is async and lands outside this orchestrator (Phase 5).
    """

    def __init__(
        self,
        harness: AgentHarnessPort,
        scorer: ScoringPort,
        persistence: PersistencePort,
        suite_source: EvalSuiteSourcePort,
        clock: Callable[[], str] = _default_clock,
    ) -> None:
        self._harness = harness
        self._scorer = scorer
        self._persistence = persistence
        self._suite_source = suite_source
        self._clock = clock

    def run_trial(
        self,
        trial_id: str,
        package: Package,
        eval_suite_ref: EvalSuiteRef,
        version_vector: VersionVector,
    ) -> Trial:
        trial = Trial(
            trial_id=trial_id,
            package=package,
            eval_suite_ref=eval_suite_ref,
            version_vector=version_vector,
        )
        self._persistence.save_trial(trial)

        self._emit(
            trial,
            TrialEvent(
                phase="configured",
                timestamp=self._clock(),
                payload={"package_model": package.model},
            ),
        )

        problems = self._suite_source.load()
        per_problem_metrics: list[Metrics] = []
        for problem in problems:
            telemetry = self._harness.run(package, problem, problem.workspace_dir)
            metrics = self._scorer.score_objective(telemetry)
            per_problem_metrics.append(metrics)

            self._emit(
                trial,
                TrialEvent(
                    phase="eval",
                    timestamp=self._clock(),
                    payload={
                        "problem_id": problem.id,
                        "exit_code": telemetry.exit_code,
                    },
                ),
            )
            self._emit(
                trial,
                TrialEvent(
                    phase="scored_objective",
                    timestamp=self._clock(),
                    payload={
                        "problem_id": problem.id,
                        "tokens_consumed": metrics.tokens_consumed,
                        "validation_pass_rate": metrics.validation_pass_rate,
                        "quality_score": metrics.quality_score,
                    },
                ),
            )

        final_metrics = _aggregate(per_problem_metrics)
        trial.final_metrics = final_metrics
        self._emit(
            trial,
            TrialEvent(
                phase="finalized",
                timestamp=self._clock(),
                payload={
                    "tokens_consumed": final_metrics.tokens_consumed,
                    "validation_pass_rate": final_metrics.validation_pass_rate,
                    "quality_score": final_metrics.quality_score,
                },
            ),
        )

        self._persistence.finalize_trial(trial.trial_id, final_metrics)
        return trial

    def _emit(self, trial: Trial, event: TrialEvent) -> None:
        trial.events.append(event)
        self._persistence.append_event(trial.trial_id, event)


def _aggregate(metrics: list[Metrics]) -> Metrics:
    if not metrics:
        return Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0)
    n = len(metrics)
    return Metrics(
        tokens_consumed=sum(m.tokens_consumed for m in metrics),
        validation_pass_rate=sum(m.validation_pass_rate for m in metrics) / n,
        quality_score=sum(m.quality_score for m in metrics) / n,
    )
