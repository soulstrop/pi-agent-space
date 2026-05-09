"""Phase 3.4 optimizer driver.

Loops: load history → propose → run trial → persist → recompute
frontier. Bounded by a trial budget; halts gracefully when the
proposer is exhausted (exhaustion = the slot space's Cartesian
product is fully covered by history).

Configuration parameters track the ADRs:

* ``per_trial_cost_cap_usd`` / ``per_run_cost_cap_usd`` (ADR 0005) —
  declared here for API stability; enforcement (warning + hard-stop
  watchdog producing ``boundary_violation`` outcomes) lands in a
  follow-up commit.
* ``replicates`` (ADR 0006) — only ``replicates=1`` is supported in
  this commit; ``>1`` will trigger fixed-N replication when wired.
* ``bootstrap_threshold`` (ADR 0006) — the proposer doesn't currently
  consult it (Phase 3.2 is uniform random throughout); Phase 6's
  surrogate proposer is what makes this load-bearing.
* ``max_consecutive_errors`` / ``max_time_without_completed_trial``
  (ADR 0007) — circuit-breaker thresholds; declared here, enforced in
  a follow-up commit.
* ``retry_budget`` (ADR 0007) — adapter-layer retry count; declared
  here, enforced in a follow-up commit.

This commit lands the loop and frontier-update mechanics. The
parameters are stable seams future commits fill in.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from .domain.pareto import pareto_frontier
from .domain.types import EvalSuiteRef, Trial, VersionVector
from .ports.package_proposer_port import PackageProposerPort
from .ports.persistence_port import PersistencePort
from .trial_runner import TrialRunner


@dataclass(frozen=True)
class OptimizerResult:
    """In-memory summary of a driver run."""

    trials: list[Trial]
    frontier_trial_ids: list[str]
    halted_reason: str  # "budget" | "exhausted"


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

    def run(self, trial_budget: int) -> OptimizerResult:
        history = self._persistence.load_trials()
        new_trials: list[Trial] = []
        halted_reason = "budget"

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
            )
            new_trials.append(trial)

            frontier_ids = [
                t.trial_id for t in pareto_frontier(history + new_trials)
            ]
            self._persistence.save_frontier(frontier_ids)

        final_frontier = pareto_frontier(history + new_trials)
        return OptimizerResult(
            trials=new_trials,
            frontier_trial_ids=[t.trial_id for t in final_frontier],
            halted_reason=halted_reason,
        )
