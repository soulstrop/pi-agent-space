"""Phase 4.3 / ADR 0012: CapabilityProfile derivation from a trial's events.

The aggregator is a free function over ``Trial`` — it filters ``metric_record``
events, joins them with ``eval`` events for per-problem ``difficulty``, and
produces per-axis summaries (mean, variance, p95, n_samples, scaling_slope).

The "aggregation re-derivable from events.jsonl alone" criterion is what
these tests pin down: no external suite lookup, no precomputed mapping.
"""

from __future__ import annotations

import math

import pytest
from builders import make_eval_suite_ref, make_version_vector

from pi_evaluator.domain.capability_profile import (
    CapabilityProfile,
    MetricSummary,
    capability_profile,
)
from pi_evaluator.domain.types import (
    Package,
    Trial,
    TrialEvent,
)


def _trial(events: list[TrialEvent]) -> Trial:
    return Trial(
        trial_id="t-1",
        package=Package(
            model="m", system_prompt="", skills=[], template_values={}
        ),
        eval_suite_ref=make_eval_suite_ref(suite_id="s", suite_version="1.0"),
        version_vector=make_version_vector(
            pi_version="0.7", package_versions={}, eval_suite_version="1.0"
        ),
        events=events,
    )


def _eval(problem_id: str, difficulty: int, exit_code: int = 0) -> TrialEvent:
    return TrialEvent(
        phase="eval",
        timestamp="t",
        payload={
            "problem_id": problem_id,
            "difficulty": difficulty,
            "exit_code": exit_code,
        },
    )


def _record(
    problem_id: str, metric_name: str, value: float | int, n_samples: int = 1
) -> TrialEvent:
    return TrialEvent(
        phase="metric_record",
        timestamp="t",
        payload={
            "problem_id": problem_id,
            "metric_name": metric_name,
            "value": value,
            "n_samples": n_samples,
        },
    )


def test_empty_trial_returns_empty_profile():
    profile = capability_profile(_trial([]))
    assert profile == CapabilityProfile(per_metric={})


def test_single_problem_summary_is_trivial():
    """One problem, one record per metric: mean=value, variance=0, p95=value,
    n_samples=1, slope=0 (slope undefined with <2 difficulty levels)."""
    events = [
        _eval("p1", difficulty=1),
        _record("p1", "cost_dollars", 0.012),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["cost_dollars"]
    assert summary == MetricSummary(
        mean=0.012,
        variance=0.0,
        p95=0.012,
        n_samples=1,
        scaling_slope=0.0,
    )


def test_scaling_slope_is_zero_for_flat_trial():
    """Same value across difficulties → slope = 0."""
    events = [
        _eval("p1", difficulty=1),
        _eval("p2", difficulty=2),
        _eval("p3", difficulty=3),
        _record("p1", "quality_score", 0.9),
        _record("p2", "quality_score", 0.9),
        _record("p3", "quality_score", 0.9),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["quality_score"]
    assert summary.scaling_slope == pytest.approx(0.0)
    assert summary.mean == pytest.approx(0.9)
    assert summary.variance == pytest.approx(0.0)


def test_scaling_slope_positive_for_cost_explosion():
    """Cost grows linearly with difficulty → positive slope."""
    events = [
        _eval("p1", difficulty=1),
        _eval("p2", difficulty=2),
        _eval("p3", difficulty=3),
        _record("p1", "cost_dollars", 0.01),
        _record("p2", "cost_dollars", 0.05),
        _record("p3", "cost_dollars", 0.20),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["cost_dollars"]
    # OLS through (1, .01), (2, .05), (3, .20): slope = (0.20 - 0.01) / 2 + adjustment
    # mean_d=2, mean_v=0.0867; num=(1-2)*(.01-.0867)+(2-2)*(.05-.0867)+(3-2)*(.20-.0867)
    # num = 0.0767 + 0 + 0.1133 = 0.19; den = 1 + 0 + 1 = 2; slope = 0.095
    assert summary.scaling_slope == pytest.approx(0.095, abs=1e-6)
    assert summary.scaling_slope > 0


def test_scaling_slope_negative_for_quality_degradation():
    """Quality drops with difficulty → negative slope."""
    events = [
        _eval("p1", difficulty=1),
        _eval("p2", difficulty=2),
        _eval("p3", difficulty=3),
        _record("p1", "quality_score", 1.0),
        _record("p2", "quality_score", 0.5),
        _record("p3", "quality_score", 0.0),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["quality_score"]
    assert summary.scaling_slope == pytest.approx(-0.5, abs=1e-6)


def test_summary_variance_and_p95_across_problems():
    """With three problems, summary stats span the data points."""
    events = [
        _eval("p1", difficulty=1),
        _eval("p2", difficulty=2),
        _eval("p3", difficulty=3),
        _record("p1", "tokens_consumed", 100),
        _record("p2", "tokens_consumed", 200),
        _record("p3", "tokens_consumed", 300),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["tokens_consumed"]
    assert summary.mean == pytest.approx(200.0)
    # Population variance: ((100-200)^2 + 0 + (300-200)^2) / 3 = 20000/3
    assert summary.variance == pytest.approx(20000.0 / 3.0)
    # Linear interpolation p95: position 1.9 in sorted [100, 200, 300]
    # = 200 + 0.9 * (300 - 200) = 290
    assert summary.p95 == pytest.approx(290.0)
    assert summary.n_samples == 3


def test_aggregation_keys_match_emitted_metric_names():
    events = [
        _eval("p1", difficulty=1),
        _record("p1", "tokens_consumed", 100),
        _record("p1", "cost_dollars", 0.01),
        _record("p1", "validation_pass_rate", 1.0),
        _record("p1", "quality_score", 0.95),
    ]
    profile = capability_profile(_trial(events))
    assert set(profile.per_metric) == {
        "tokens_consumed",
        "cost_dollars",
        "validation_pass_rate",
        "quality_score",
    }


def test_scaling_slope_zero_when_difficulties_collapse():
    """Two problems at the same difficulty → slope = 0 (no variation in x)."""
    events = [
        _eval("p1", difficulty=2),
        _eval("p2", difficulty=2),
        _record("p1", "cost_dollars", 0.10),
        _record("p2", "cost_dollars", 0.50),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["cost_dollars"]
    assert summary.scaling_slope == pytest.approx(0.0)
    # Mean / variance are still meaningful.
    assert summary.mean == pytest.approx(0.30)
    assert summary.variance > 0


def test_profile_ignores_non_metric_events():
    """configured, finalized, boundary_violation events should not pollute
    aggregation."""
    events = [
        TrialEvent(phase="configured", timestamp="t", payload={}),
        _eval("p1", difficulty=1),
        _record("p1", "cost_dollars", 0.01),
        TrialEvent(phase="boundary_violation", timestamp="t", payload={}),
        TrialEvent(phase="finalized", timestamp="t", payload={}),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["cost_dollars"]
    assert summary.n_samples == 1


def test_no_inf_or_nan_on_degenerate_input():
    """Single zero-valued metric should not produce inf/NaN."""
    events = [
        _eval("p1", difficulty=1),
        _record("p1", "cost_dollars", 0.0),
    ]
    profile = capability_profile(_trial(events))
    summary = profile.per_metric["cost_dollars"]
    assert not math.isnan(summary.scaling_slope)
    assert not math.isinf(summary.scaling_slope)
    assert not math.isnan(summary.variance)
    assert not math.isnan(summary.p95)
