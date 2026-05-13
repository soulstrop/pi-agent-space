"""Phase 3.4 optimizer driver.

Loops: load history → propose → run trial → persist → recompute
frontier. Bounded by a trial budget; halts gracefully when the
proposer is exhausted (exhaustion = the slot space's Cartesian
product is fully covered by history).

Configuration parameters track the ADRs:

* ``per_trial_cost_cap_usd`` / ``per_run_cost_cap_usd`` (ADR 0005) —
  the per-trial cap is forwarded to ``TrialRunner.run_trial`` and
  trips an in-trial watchdog that produces ``boundary_violation``
  outcomes; the per-run cap is enforced here between trials and
  halts the driver with ``halted_reason="per_run_cost_cap"``.
* ``replicates`` (ADR 0006) — only ``replicates=1`` is supported in
  this commit; ``>1`` will trigger fixed-N replication when wired.
* ``bootstrap_threshold`` (ADR 0006) — the proposer doesn't currently
  consult it (Phase 3.2 is uniform random throughout); Phase 6's
  surrogate proposer is what makes this load-bearing.
* ``max_consecutive_errors`` / ``max_time_without_completed_trial``
  (ADR 0007) — circuit-breaker thresholds. Trip with
  ``halted_reason="circuit_breaker_errors"`` /
  ``"circuit_breaker_time"`` respectively. ``boundary_violation``
  outcomes neither increment nor reset the consecutive-errors counter
  (only ``completed`` resets it, only ``error_escalated`` increments).
* ``retry_budget`` (ADR 0007) — adapter-layer retry count; declared
  here, enforced in a follow-up commit.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from .domain.pareto import pareto_frontier
from .domain.types import EvalSuiteRef, Trial, VersionVector
from .ports.package_proposer_port import PackageProposerPort
from .ports.persistence_port import PersistencePort
from .trial_runner import COST_CAP_WARNING_FRACTION, TrialRunner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimizerResult:
    """In-memory summary of a driver run."""

    trials: list[Trial]
    frontier_trial_ids: list[str]
    halted_reason: str
    # "budget" | "exhausted" | "per_run_cost_cap"
    # | "circuit_breaker_errors" | "circuit_breaker_time"


def _default_trial_id_factory() -> str:
    return str(uuid.uuid4())


class OptimizerDriver:
    def __init__(
        self,
        runner: TrialRunner,
        proposer: PackageProposerPort,
        persistence: PersistencePort,
        eval_suite_ref: EvalSuiteRef,
        version_vector: VersionVector,
        per_trial_cost_cap_usd: float | None = None,
        per_run_cost_cap_usd: float | None = None,
        replicates: int = 1,
        bootstrap_threshold: int = 10,
        max_consecutive_errors: int | None = None,
        max_time_without_completed_trial: timedelta | None = None,
        retry_budget: int = 2,
        trial_id_factory: Callable[[], str] = _default_trial_id_factory,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if replicates != 1:
            raise NotImplementedError(
                f"replicates>{1} not yet supported (got {replicates}); "
                "fixed-N replication lands in a follow-up commit."
            )
        self._runner = runner
        self._proposer = proposer
        self._persistence = persistence
        self._eval_suite_ref = eval_suite_ref
        self._version_vector = version_vector
        self._per_trial_cost_cap_usd = per_trial_cost_cap_usd
        self._per_run_cost_cap_usd = per_run_cost_cap_usd
        self._replicates = replicates
        self._bootstrap_threshold = bootstrap_threshold
        self._max_consecutive_errors = max_consecutive_errors
        self._max_time_without_completed_trial = max_time_without_completed_trial
        self._retry_budget = retry_budget
        self._trial_id_factory = trial_id_factory
        self._monotonic_clock = monotonic_clock

    def run(self, trial_budget: int) -> OptimizerResult:
        history = self._persistence.load_trials()
        new_trials: list[Trial] = []
        halted_reason = "budget"
        run_warning_emitted = False
        consecutive_errors = 0
        last_completed_at = self._monotonic_clock()

        for _ in range(trial_budget):
            package = self._proposer.propose(history + new_trials)
            if package is None:
                halted_reason = "exhausted"
                break

            trial = self._runner.run_trial(
                trial_id=self._trial_id_factory(),
                package=package,
                eval_suite_ref=self._eval_suite_ref,
                version_vector=self._version_vector,
                per_trial_cost_cap_usd=self._per_trial_cost_cap_usd,
            )
            new_trials.append(trial)

            frontier_ids = [
                t.trial_id for t in pareto_frontier(history + new_trials)
            ]
            self._persistence.save_frontier(frontier_ids)

            now = self._monotonic_clock()
            if trial.outcome == "completed":
                consecutive_errors = 0
                last_completed_at = now
            elif trial.outcome == "error_escalated":
                consecutive_errors += 1
            # boundary_violation: leave counter and last_completed_at alone.

            if (
                self._max_consecutive_errors is not None
                and consecutive_errors >= self._max_consecutive_errors
            ):
                halted_reason = "circuit_breaker_errors"
                break

            if self._max_time_without_completed_trial is not None:
                elapsed = now - last_completed_at
                if elapsed > self._max_time_without_completed_trial.total_seconds():
                    halted_reason = "circuit_breaker_time"
                    break

            if self._per_run_cost_cap_usd is not None:
                cumulative = sum(
                    t.final_metrics.cost_dollars
                    for t in new_trials
                    if t.final_metrics is not None
                )
                warning_threshold = (
                    self._per_run_cost_cap_usd * COST_CAP_WARNING_FRACTION
                )
                if (
                    not run_warning_emitted
                    and cumulative > warning_threshold
                ):
                    logger.warning(
                        "Per-run cost cap warning: cumulative=$%.4f exceeds "
                        "%.0f%% of cap $%.4f",
                        cumulative,
                        COST_CAP_WARNING_FRACTION * 100,
                        self._per_run_cost_cap_usd,
                    )
                    run_warning_emitted = True
                if cumulative > self._per_run_cost_cap_usd:
                    halted_reason = "per_run_cost_cap"
                    break

        final_frontier = pareto_frontier(history + new_trials)
        return OptimizerResult(
            trials=new_trials,
            frontier_trial_ids=[t.trial_id for t in final_frontier],
            halted_reason=halted_reason,
        )
