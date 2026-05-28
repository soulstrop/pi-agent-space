"""Phase 4 acceptance test: scaling-slope distinguishes scaling-poor configs.

Per implementation-plan.md Phase 4.5 and ADR 0012, the ``scaling_slope`` axis on
``cost_dollars`` should distinguish a "uniformly moderate" trial from a
"cheap-then-explodes" trial. With all other Pareto axes tied, the 4D frontier
must exclude the cliffy trial.

This is a deterministic stub-based test rather than an ``acceptance_full``
real-Pi exercise: the per-problem cost is fed via a ``_DifficultyKeyedScorer``
that pops metrics off a suite-order queue, so we can pre-program the cost cliff
without relying on a particular model's behavior. The real-Pi acceptance for
Phase 4's slope-discrimination behavior is best validated as part of Phase 6's
surrogate work (which actually consumes the slope axis), so we don't open an
``acceptance_full`` variant here.

The test exercises the real ``GraduatedProblemSetAdapter`` against the real
``graduated_problems/`` directory (001/002/003), so the suite-loading and
difficulty-ordering integration is honest. The harness is stubbed because the
Phase 4 contract is about the events → profile → frontier pipeline, not about
provider behavior.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.domain.capability_profile import capability_profile
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
    """Returns pre-programmed metrics in suite-order, one per call.

    Lets the test feed a specific cost-vs-difficulty curve into the trial
    runner. The adapter loads problems in sorted directory order
    (``001_*``, ``002_*``, ``003_*``) which happens to match ascending
    difficulty by convention; callers supply metrics in that order.
    """

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
    return EvalSuiteRef(suite_id="coding_v1", suite_version="phase4")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.74.0",
        package_versions={},
        eval_suite_version="phase4",
    )


def _run_trial(
    persist_root: Path,
    trial_id: str,
    costs_in_suite_order: list[float],
) -> Trial:
    """Run a trial against the real 3-problem suite with controlled
    per-problem cost. Tokens / pass rate / quality are constant so the
    only meaningful Pareto-axis difference between scenarios is
    ``cost_dollars`` mean and slope."""
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
        clock=lambda c=itertools.count(): f"2026-05-28T00:00:{next(c):02d}Z",
    )
    return runner.run_trial(trial_id, _package(), _suite_ref(), _versions())


def test_scaling_slope_distinguishes_flat_from_cliffy(tmp_path):
    """ADR 0012 4D Pareto: with means tied, slope is the decider.

    Float-exact inputs: ``[3.0, 3.0, 3.0]`` and ``[1.0, 3.0, 5.0]`` both
    sum to 9.0 and average to 3.0 bit-for-bit, so the means tie and any
    Pareto separation must be driven by ``scaling_slope``.
    """
    flat = _run_trial(tmp_path / "flat", "t-flat", [3.0, 3.0, 3.0])
    cliffy = _run_trial(tmp_path / "cliffy", "t-cliffy", [1.0, 3.0, 5.0])

    flat_profile = capability_profile(flat)
    cliffy_profile = capability_profile(cliffy)

    # Cost-cliff signal: flat's slope is zero; cliffy's is strictly positive.
    assert flat_profile.per_metric["cost_dollars"].scaling_slope == pytest.approx(0.0)
    assert cliffy_profile.per_metric["cost_dollars"].scaling_slope > 0.0

    # Means tie by construction so the slope axis is the decider.
    assert flat_profile.per_metric["cost_dollars"].mean == pytest.approx(3.0)
    assert cliffy_profile.per_metric["cost_dollars"].mean == pytest.approx(3.0)

    # 4D Pareto: flat strictly dominates cliffy.
    frontier = pareto_frontier([flat, cliffy])
    assert {t.trial_id for t in frontier} == {"t-flat"}


def test_phase4_event_stream_shape(tmp_path):
    """ADR 0012 emission shape per problem: eval + 4 × metric_record."""
    trial = _run_trial(tmp_path / "shape", "t-shape", [3.0, 3.0, 3.0])
    phases = [e.phase for e in trial.events]
    per_problem = ["eval"] + ["metric_record"] * 4
    assert phases == ["configured"] + per_problem * 3 + ["finalized"]


def test_capability_profile_records_token_slope_diagnostics(tmp_path):
    """ADR 0012 consequences: tokens-slope is computed for diagnostics but is
    not a Pareto axis in v1. Confirm it's present and minimization-correct."""
    # Tokens grow with difficulty too; the profile should record a positive
    # slope on tokens, but pareto_frontier (above) ignores it.
    metrics = [
        Metrics(
            tokens_consumed=t,
            cost_dollars=1.0,
            validation_pass_rate=0.5,
            quality_score=0.5,
        )
        for t in (10, 100, 1000)
    ]
    runner = TrialRunner(
        harness=StubAgentHarnessAdapter(),
        scorer=_DifficultyKeyedScorer(metrics),
        persistence=PerTrialDirectoryAdapter(tmp_path),
        suite_source=GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR),
        clock=lambda c=itertools.count(): f"2026-05-28T00:00:{next(c):02d}Z",
    )
    trial = runner.run_trial("t-tokslope", _package(), _suite_ref(), _versions())
    profile = capability_profile(trial)
    assert profile.per_metric["tokens_consumed"].scaling_slope > 0.0
