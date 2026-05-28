"""Trial orchestrator: composes the four Phase 1 ports into a pipeline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .domain.types import (
    EvalSuiteRef,
    Metrics,
    Outcome,
    Package,
    RawTelemetry,
    Trial,
    TrialEvent,
    VersionVector,
)
from .lifecycle import classify_outcome
from .ports.agent_harness_port import AgentHarnessPort
from .ports.eval_suite_source_port import EvalSuiteSourcePort
from .ports.persistence_port import PersistencePort
from .ports.scoring_port import ScoringPort

COST_CAP_WARNING_FRACTION = 0.8
"""ADR 0005 soft-warning threshold expressed as a fraction of the hard cap.

A fixed v1 constant rather than a per-call parameter — keeps the cap
API one-knob. Reconsider when operators ask for asymmetric warning /
hard-stop bands (e.g., warn at 50%, halt at 100%)."""


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
        per_trial_cost_cap_usd: float | None = None,
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
        per_problem_telemetry: list[RawTelemetry] = []
        cumulative_cost = 0.0
        warning_emitted = False
        for problem in problems:
            telemetry = self._harness.run(package, problem, problem.workspace_dir)
            metrics = self._scorer.score_objective(telemetry)
            per_problem_metrics.append(metrics)
            per_problem_telemetry.append(telemetry)
            cumulative_cost += metrics.cost_dollars

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
                        "cost_dollars": metrics.cost_dollars,
                        "validation_pass_rate": metrics.validation_pass_rate,
                        "quality_score": metrics.quality_score,
                    },
                ),
            )

            if per_trial_cost_cap_usd is not None:
                warning_threshold = (
                    per_trial_cost_cap_usd * COST_CAP_WARNING_FRACTION
                )
                if not warning_emitted and cumulative_cost > warning_threshold:
                    self._emit(
                        trial,
                        TrialEvent(
                            phase="cost_cap_warning",
                            timestamp=self._clock(),
                            payload={
                                "scope": "per_trial",
                                "cap_usd": per_trial_cost_cap_usd,
                                "cumulative_cost_dollars": cumulative_cost,
                                "fraction": COST_CAP_WARNING_FRACTION,
                            },
                        ),
                    )
                    warning_emitted = True
                if cumulative_cost > per_trial_cost_cap_usd:
                    self._emit(
                        trial,
                        TrialEvent(
                            phase="boundary_violation",
                            timestamp=self._clock(),
                            payload={
                                "reason": "per_trial_cost_cap",
                                "cap_usd": per_trial_cost_cap_usd,
                                "cumulative_cost_dollars": cumulative_cost,
                            },
                        ),
                    )
                    break

        outcome: Outcome = classify_outcome(trial.events, per_problem_telemetry)
        if outcome == "boundary_violation":
            final_metrics = Metrics(
                tokens_consumed=sum(m.tokens_consumed for m in per_problem_metrics),
                cost_dollars=sum(m.cost_dollars for m in per_problem_metrics),
                validation_pass_rate=0.0,
                quality_score=0.0,
            )
        else:
            final_metrics = _aggregate(per_problem_metrics)
        trial.final_metrics = final_metrics
        trial.outcome = outcome
        self._emit(
            trial,
            TrialEvent(
                phase="finalized",
                timestamp=self._clock(),
                payload={
                    "tokens_consumed": final_metrics.tokens_consumed,
                    "cost_dollars": final_metrics.cost_dollars,
                    "validation_pass_rate": final_metrics.validation_pass_rate,
                    "quality_score": final_metrics.quality_score,
                    "outcome": outcome,
                },
            ),
        )

        self._persistence.finalize_trial(trial.trial_id, final_metrics, outcome)
        return trial

    def _emit(self, trial: Trial, event: TrialEvent) -> None:
        trial.events.append(event)
        self._persistence.append_event(trial.trial_id, event)


def _aggregate(metrics: list[Metrics]) -> Metrics:
    if not metrics:
        return Metrics(
            tokens_consumed=0,
            cost_dollars=0.0,
            validation_pass_rate=0.0,
            quality_score=0.0,
        )
    n = len(metrics)
    return Metrics(
        tokens_consumed=sum(m.tokens_consumed for m in metrics),
        cost_dollars=sum(m.cost_dollars for m in metrics),
        validation_pass_rate=sum(m.validation_pass_rate for m in metrics) / n,
        quality_score=sum(m.quality_score for m in metrics) / n,
    )


