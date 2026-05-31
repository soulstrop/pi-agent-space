"""Phase 5 acceptance test: 5D Pareto with subjective axis.

Per implementation-plan.md Phase 5.4, the Pareto frontier lifts from 4D to 5D
once subjective scores are present. The 5.3 partial-score policy governs how
unscored trials participate: they are excluded from subjective-axis dominance
(neither can dominate nor be dominated on that axis) but remain eligible on
the 4D objective axes.

Like the Phase 4 acceptance test, this is a deterministic stub-based exercise:
``_DifficultyKeyedScorer`` feeds controlled per-problem metrics so the
objective axes are fully predictable. Subjective scores are attached out-of-
band via ``write_subjective_score``, mimicking the ``pi-eval score`` CLI path.
The harness is stubbed because Phase 5's contract is about the
score → persist → load → frontier pipeline, not provider behaviour.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.domain.pareto import pareto_frontier
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RawTelemetry,
    SubjectiveScore,
    Trial,
    VersionVector,
)
from pi_evaluator.trial_runner import TrialRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"


class _DifficultyKeyedScorer:
    """Returns pre-programmed per-problem metrics in suite order."""

    def __init__(self, metrics_in_suite_order: list[Metrics]) -> None:
        self._queue = list(metrics_in_suite_order)

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        return self._queue.pop(0)

    def score_subjective(self, trial: Trial) -> SubjectiveScore | None:
        return None


def _package() -> Package:
    return Package(
        model="anthropic/claude-haiku-4-5",
        system_prompt="x",
        skills=["read"],
        template_values={},
    )


def _suite_ref() -> EvalSuiteRef:
    return EvalSuiteRef(suite_id="coding_v1", suite_version="phase5")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.74.0",
        package_versions={},
        eval_suite_version="phase5",
    )


def _run_trial(
    persist_root: Path,
    trial_id: str,
    costs_in_suite_order: list[float],
) -> Trial:
    """Run a trial with controlled per-problem cost; tokens / quality constant."""
    metrics_per_problem = [
        Metrics(
            tokens_consumed=100,
            cost_dollars=c,
            validation_pass_rate=0.5,
            quality_score=0.5,
        )
        for c in costs_in_suite_order
    ]
    runner = TrialRunner(
        harness=StubAgentHarnessAdapter(),
        scorer=_DifficultyKeyedScorer(metrics_per_problem),
        persistence=PerTrialDirectoryAdapter(persist_root),
        suite_source=GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR),
        clock=lambda c=itertools.count(): f"2026-05-30T00:00:{next(c):02d}Z",
    )
    return runner.run_trial(trial_id, _package(), _suite_ref(), _versions())


def _ss(score: float, scorer: str = "user:tester") -> SubjectiveScore:
    return SubjectiveScore(score=score, notes="", scorer=scorer, timestamp="t")


def test_5d_higher_subjective_dominates_lower_when_objectives_tied(tmp_path):
    """When two completed trials tie on all 4 objective axes and both receive
    subjective scores, the one with the higher score dominates in 5D.

    Float-exact inputs: [3.0, 3.0, 3.0] gives mean=3.0 and slope=0.0
    bit-for-bit for both trials.
    """
    persist = tmp_path / "store"
    _run_trial(persist, "t-high", [3.0, 3.0, 3.0])
    _run_trial(persist, "t-low", [3.0, 3.0, 3.0])

    adapter = PerTrialDirectoryAdapter(persist)
    adapter.write_subjective_score("t-high", _ss(0.9))
    adapter.write_subjective_score("t-low", _ss(0.3))

    trials = adapter.load_trials()
    frontier = pareto_frontier(trials)
    assert {t.trial_id for t in frontier} == {"t-high"}


def test_5d_unscored_trial_not_excluded_by_scored_when_objectives_tied(tmp_path):
    """An unscored trial cannot be dominated on the subjective axis (5.3 policy).

    When two trials tie on the 4 objective axes but only one has a subjective
    score, both remain on the frontier — the scored trial cannot claim strict
    improvement via an axis that the other trial doesn't participate in.
    """
    persist = tmp_path / "store"
    _run_trial(persist, "t-scored", [3.0, 3.0, 3.0])
    _run_trial(persist, "t-unscored", [3.0, 3.0, 3.0])

    adapter = PerTrialDirectoryAdapter(persist)
    adapter.write_subjective_score("t-scored", _ss(0.9))

    trials = adapter.load_trials()
    frontier = pareto_frontier(trials)
    assert {t.trial_id for t in frontier} == {"t-scored", "t-unscored"}


def test_5d_objective_dominance_unchanged_for_unscored_trials(tmp_path):
    """4D objective dominance is preserved in Phase 5.4.

    A trial that dominates on all 4 objective axes displaces the other
    regardless of whether either has a subjective score.
    """
    persist = tmp_path / "store"
    # flat: mean=3.0, slope=0; cheap: mean=1.0, slope=0
    _run_trial(persist, "t-cheap", [1.0, 1.0, 1.0])
    _run_trial(persist, "t-expensive", [5.0, 5.0, 5.0])

    adapter = PerTrialDirectoryAdapter(persist)
    trials = adapter.load_trials()
    # No subjective scores: pure 4D. t-cheap dominates on cost axes.
    frontier = pareto_frontier(trials)
    assert {t.trial_id for t in frontier} == {"t-cheap"}


def test_transition_objective_only_to_fully_scored(tmp_path):
    """Demonstrates the Phase 5 lifecycle: frontier starts at 4D with both
    trials non-dominating, then lifts to 5D after subjective scoring makes one
    trial strictly dominant.
    """
    persist = tmp_path / "store"
    _run_trial(persist, "t-a", [3.0, 3.0, 3.0])
    _run_trial(persist, "t-b", [3.0, 3.0, 3.0])

    adapter = PerTrialDirectoryAdapter(persist)

    # Phase: objective-only — both on the 4D frontier
    objective_only = adapter.load_trials()
    pre_score_frontier = pareto_frontier(objective_only)
    assert {t.trial_id for t in pre_score_frontier} == {"t-a", "t-b"}

    # Phase: add subjective scores out-of-band (simulates `pi-eval score` CLI)
    adapter.write_subjective_score("t-a", _ss(0.8))
    adapter.write_subjective_score("t-b", _ss(0.4))

    # Phase: fully-scored — higher-scored trial dominates in 5D
    fully_scored = adapter.load_trials()
    post_score_frontier = pareto_frontier(fully_scored)
    assert {t.trial_id for t in post_score_frontier} == {"t-a"}
