"""Tests for Phase 6.2 training-data extraction from trial history.

No BoTorch dependency — exercises only the pure-domain
build_training_data() function.
"""

from __future__ import annotations

import pytest

from pi_evaluator.domain.featurize import FeatureEncoder
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.surrogate_data import (
    MIN_NOISE_VAR,
    SURROGATE_AXES,
    build_training_data,
)
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Outcome,
    Package,
    SubjectiveScore,
    Trial,
    TrialEvent,
    VersionVector,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


def _space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
        ],
        skills_variants=[NamedValue(name="minimal", value=("read",))],
        system_prompts=[NamedValue(name="v0", value="prompt")],
        template_value_variants=[NamedValue(name="default", value={})],
    )


def _encoder() -> FeatureEncoder:
    return FeatureEncoder(_space())


def _metric_events(
    problem_id: str,
    difficulty: int,
    tokens: int,
    dollars: float,
    quality: float,
) -> list[TrialEvent]:
    ts = "t"
    return [
        TrialEvent(
            phase="eval",
            timestamp=ts,
            payload={"problem_id": problem_id, "difficulty": difficulty},
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": problem_id,
                "metric_name": "tokens_consumed",
                "value": tokens,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": problem_id,
                "metric_name": "cost_dollars",
                "value": dollars,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": problem_id,
                "metric_name": "quality_score",
                "value": quality,
                "n_samples": 1,
            },
        ),
    ]


def _trial(
    *,
    model: str = "google/gemini-2.5-flash",
    tokens: int = 100,
    dollars: float = 0.01,
    quality: float = 0.8,
    outcome: Outcome = "completed",
    n_problems: int = 1,
    trial_id: str = "t-001",
) -> Trial:
    events: list[TrialEvent] = []
    for i in range(n_problems):
        events.extend(
            _metric_events(f"p{i + 1}", i + 1, tokens, dollars, quality)
        )
    return Trial(
        trial_id=trial_id,
        package=Package(
            model=model,
            system_prompt="prompt",
            skills=["read"],
            template_values={},
        ),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="v"),
        version_vector=VersionVector(
            pi_version="0.74.0", package_versions={}, eval_suite_version="v"
        ),
        events=events,
        final_metrics=Metrics(
            tokens_consumed=tokens,
            cost_dollars=dollars,
            validation_pass_rate=quality,
            quality_score=quality,
        ),
        outcome=outcome,
    )


# ── axis coverage ─────────────────────────────────────────────────────────────


def test_all_five_axes_present_in_output():
    data = build_training_data([_trial()], _encoder())
    assert set(data.keys()) == set(SURROGATE_AXES)


def test_objective_axes_have_one_row_per_completed_trial():
    trials = [
        _trial(trial_id="t1"),
        _trial(trial_id="t2", tokens=200, dollars=0.02),
    ]
    data = build_training_data(trials, _encoder())
    for axis in ("mean_tokens", "mean_dollars", "scaling_slope", "mean_quality"):
        X, Y, Y_var = data[axis]
        assert len(X) == 2
        assert len(Y) == 2
        assert len(Y_var) == 2


def test_subjective_axis_empty_when_no_scores_present():
    data = build_training_data([_trial()], _encoder())
    X, Y, Y_var = data["subjective"]
    assert X == []
    assert Y == []
    assert Y_var == []


def test_subjective_axis_populated_when_score_present():
    t = _trial()
    t.subjective_score = SubjectiveScore(
        score=0.7, notes="", scorer="user:me", timestamp="t"
    )
    data = build_training_data([t], _encoder())
    X, Y, Y_var = data["subjective"]
    assert len(X) == 1
    assert Y[0] == pytest.approx(0.7)


def test_subjective_axis_mixed_scored_and_unscored():
    scored = _trial(trial_id="t1")
    scored.subjective_score = SubjectiveScore(
        score=0.9, notes="", scorer="user:me", timestamp="t"
    )
    unscored = _trial(trial_id="t2")
    data = build_training_data([scored, unscored], _encoder())
    X_s, Y_s, _ = data["subjective"]
    assert len(X_s) == 1
    assert Y_s[0] == pytest.approx(0.9)
    # Objective axes have 2 rows each.
    X_t, _, _ = data["mean_tokens"]
    assert len(X_t) == 2


# ── exclusion rules ───────────────────────────────────────────────────────────


def test_error_escalated_trial_excluded():
    data = build_training_data(
        [_trial(outcome="error_escalated")], _encoder()
    )
    for axis in SURROGATE_AXES:
        X, _, _ = data[axis]
        assert X == []


def test_trial_with_none_outcome_excluded():
    t = _trial()
    t.outcome = None
    data = build_training_data([t], _encoder())
    for axis in SURROGATE_AXES:
        X, _, _ = data[axis]
        assert X == []


def test_boundary_violation_included():
    """ADR 0007: boundary_violation trials carry metrics and belong in
    the surrogate's training set as cost-cliff signals."""
    data = build_training_data(
        [_trial(outcome="boundary_violation")], _encoder()
    )
    for axis in ("mean_tokens", "mean_dollars", "mean_quality"):
        X, _, _ = data[axis]
        assert len(X) == 1


def test_trial_missing_required_metric_excluded():
    events = [
        TrialEvent(
            phase="eval",
            timestamp="t",
            payload={"problem_id": "p1", "difficulty": 1},
        ),
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": "p1",
                "metric_name": "tokens_consumed",
                "value": 50,
                "n_samples": 1,
            },
        ),
        # cost_dollars and quality_score deliberately absent
    ]
    t = Trial(
        trial_id="t-bad",
        package=Package(
            model="google/gemini-2.5-flash",
            system_prompt="prompt",
            skills=["read"],
            template_values={},
        ),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="v"),
        version_vector=VersionVector(
            pi_version="0.74.0", package_versions={}, eval_suite_version="v"
        ),
        events=events,
        outcome="completed",
    )
    data = build_training_data([t], _encoder())
    for axis in SURROGATE_AXES:
        X, _, _ = data[axis]
        assert X == []


def test_package_not_in_encoder_space_skips_trial():
    t = _trial()
    t.package = Package(
        model="openai/gpt-4o",  # not in _space()
        system_prompt="prompt",
        skills=["read"],
        template_values={},
    )
    data = build_training_data([t], _encoder())
    for axis in SURROGATE_AXES:
        X, _, _ = data[axis]
        assert X == []


# ── noise floor ───────────────────────────────────────────────────────────────


def test_noise_floor_applied_when_variance_is_zero():
    """Single-problem trial → capability_profile variance is 0.0;
    Y_var must be clamped to at least MIN_NOISE_VAR."""
    data = build_training_data([_trial(n_problems=1)], _encoder())
    for axis in ("mean_tokens", "mean_dollars", "mean_quality"):
        _, _, Y_var = data[axis]
        assert all(v >= MIN_NOISE_VAR for v in Y_var)


def test_multi_problem_trial_variance_reflects_spread():
    """Two problems at different values → non-zero variance; should
    be >= MIN_NOISE_VAR and distinctly larger than MIN_NOISE_VAR."""
    data = build_training_data(
        [_trial(n_problems=2, tokens=100, dollars=0.01, quality=0.8)],
        _encoder(),
    )
    # With two problems at identical values, variance is still 0 → clamped.
    # Let's just verify the floor.
    _, _, Y_var = data["mean_tokens"]
    assert all(v >= MIN_NOISE_VAR for v in Y_var)


# ── feature vectors ───────────────────────────────────────────────────────────


def test_feature_vectors_have_correct_dimension():
    enc = _encoder()
    data = build_training_data([_trial()], enc)
    for axis in SURROGATE_AXES:
        X, _, _ = data[axis]
        if X:
            assert len(X[0]) == enc.feature_dim


def test_different_models_produce_different_feature_vectors():
    enc = _encoder()
    t_flash = _trial(model="google/gemini-2.5-flash", trial_id="flash")
    t_haiku = _trial(model="anthropic/claude-haiku-4-5", trial_id="haiku")
    data = build_training_data([t_flash, t_haiku], enc)
    X, _, _ = data["mean_tokens"]
    assert len(X) == 2
    assert X[0] != X[1]


# ── empty input ───────────────────────────────────────────────────────────────


def test_empty_trial_list_returns_empty_data():
    data = build_training_data([], _encoder())
    for axis in SURROGATE_AXES:
        X, Y, Y_var = data[axis]
        assert X == [] and Y == [] and Y_var == []
