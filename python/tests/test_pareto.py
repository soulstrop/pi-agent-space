from __future__ import annotations

from dataclasses import replace

from pi_evaluator.domain.pareto import pareto_frontier
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Outcome,
    Package,
    Trial,
    TrialEvent,
    VersionVector,
)


def _package() -> Package:
    return Package(
        model="m",
        system_prompt="p",
        skills=["read"],
        template_values={},
    )


def _problem_events(
    problem_id: str,
    difficulty: int,
    tokens: int,
    dollars: float,
    quality: float,
) -> list[TrialEvent]:
    """Build the (eval, metric_record × 4) event block for one problem.

    Matches the shape TrialRunner emits per ADR 0012, so pareto.py exercises
    the production event-stream consumption path even from synthetic trials.
    """
    return [
        TrialEvent(
            phase="eval",
            timestamp="t",
            payload={
                "problem_id": problem_id,
                "difficulty": difficulty,
                "exit_code": 0,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": problem_id,
                "metric_name": "tokens_consumed",
                "value": tokens,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": problem_id,
                "metric_name": "cost_dollars",
                "value": dollars,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": problem_id,
                "metric_name": "validation_pass_rate",
                "value": quality,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": problem_id,
                "metric_name": "quality_score",
                "value": quality,
                "n_samples": 1,
            },
        ),
    ]


def _trial(
    trial_id: str,
    *,
    tokens: int,
    dollars: float,
    quality: float,
    outcome: Outcome | None = "completed",
    final: bool = True,
) -> Trial:
    """Single-problem trial — slope axis is 0 by construction.

    Use ``_multi_problem_trial`` for slope-sensitive tests.
    """
    events = _problem_events("p1", 1, tokens, dollars, quality) if final else []
    metrics: Metrics | None = (
        Metrics(
            tokens_consumed=tokens,
            cost_dollars=dollars,
            validation_pass_rate=quality,
            quality_score=quality,
        )
        if final
        else None
    )
    return Trial(
        trial_id=trial_id,
        package=_package(),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="v"),
        version_vector=VersionVector(
            pi_version="0.74.0", package_versions={}, eval_suite_version="v"
        ),
        events=events,
        final_metrics=metrics,
        outcome=outcome,
    )


def _multi_problem_trial(
    trial_id: str,
    *,
    per_problem: list[tuple[int, int, float, float]],
    outcome: Outcome | None = "completed",
) -> Trial:
    """Construct a multi-problem trial.

    Each tuple is ``(difficulty, tokens, dollars, quality)``; slope axes
    follow from the spread across difficulty.
    """
    events: list[TrialEvent] = []
    for idx, (difficulty, tokens, dollars, quality) in enumerate(per_problem):
        events.extend(
            _problem_events(f"p{idx + 1}", difficulty, tokens, dollars, quality)
        )
    return Trial(
        trial_id=trial_id,
        package=_package(),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="v"),
        version_vector=VersionVector(
            pi_version="0.74.0", package_versions={}, eval_suite_version="v"
        ),
        events=events,
        final_metrics=None,
        outcome=outcome,
    )


def _ids(trials: list[Trial]) -> set[str]:
    return {t.trial_id for t in trials}


def test_empty_input_yields_empty_frontier():
    assert pareto_frontier([]) == []


def test_single_trial_is_on_frontier():
    [t] = [_trial("a", tokens=100, dollars=0.1, quality=0.5)]
    assert pareto_frontier([t]) == [t]


def test_strictly_dominated_trial_is_excluded():
    winner = _trial("winner", tokens=10, dollars=0.01, quality=0.9)
    loser = _trial("loser", tokens=100, dollars=0.10, quality=0.5)
    assert _ids(pareto_frontier([winner, loser])) == {"winner"}


def test_mutually_nondominating_trials_all_on_frontier():
    cheap_low_quality = _trial("cheap", tokens=10, dollars=0.01, quality=0.3)
    expensive_high_quality = _trial("good", tokens=200, dollars=0.50, quality=0.9)
    assert _ids(pareto_frontier([cheap_low_quality, expensive_high_quality])) == {
        "cheap",
        "good",
    }


def test_token_cheap_but_dollar_expensive_stays_on_frontier():
    """ADR 0005 motivating case: keeping tokens and dollars as separate axes
    means a token-cheap-but-dollar-expensive config is not dominated by its
    mirror, and vice versa."""
    cheap_tokens = _trial("token-cheap", tokens=10, dollars=0.50, quality=0.7)
    cheap_dollars = _trial("dollar-cheap", tokens=200, dollars=0.05, quality=0.7)
    assert _ids(pareto_frontier([cheap_tokens, cheap_dollars])) == {
        "token-cheap",
        "dollar-cheap",
    }


def test_error_escalated_trial_excluded_from_frontier():
    completed = _trial("done", tokens=100, dollars=0.1, quality=0.5)
    errored = _trial(
        "errored",
        tokens=0,
        dollars=0.0,
        quality=0.0,
        outcome="error_escalated",
    )
    assert _ids(pareto_frontier([completed, errored])) == {"done"}


def test_boundary_violation_trial_included():
    """ADR 0007: boundary_violation trials carry metrics and contribute to
    the cost-cliff side of the frontier; they are not excluded."""
    completed = _trial("done", tokens=100, dollars=0.10, quality=0.9)
    bad_boundary = _trial(
        "boundary",
        tokens=10000,
        dollars=5.00,
        quality=0.0,
        outcome="boundary_violation",
    )
    frontier = pareto_frontier([completed, bad_boundary])
    # The completed trial dominates on every axis, so only it is on the frontier.
    # But the boundary trial is *eligible* — confirm by removing the dominator.
    assert _ids(frontier) == {"done"}
    [solo] = pareto_frontier([bad_boundary])
    assert solo.trial_id == "boundary"


def test_unfinalized_trial_excluded():
    completed = _trial("done", tokens=100, dollars=0.1, quality=0.5)
    open_trial = _trial(
        "open",
        tokens=0,
        dollars=0.0,
        quality=0.0,
        final=False,
        outcome=None,
    )
    assert _ids(pareto_frontier([completed, open_trial])) == {"done"}


def test_equal_metric_duplicates_both_included():
    a = _trial("a", tokens=100, dollars=0.10, quality=0.5)
    b = replace(a, trial_id="b")
    # No strict domination between equal-metric trials.
    assert _ids(pareto_frontier([a, b])) == {"a", "b"}


def test_three_axis_tradeoff():
    """Verify that genuine 3D trade-offs all stay on the frontier:
    each trial wins on exactly one axis."""
    token_winner = _trial("tokens", tokens=10, dollars=0.50, quality=0.5)
    dollar_winner = _trial("dollars", tokens=100, dollars=0.01, quality=0.5)
    quality_winner = _trial("quality", tokens=100, dollars=0.50, quality=0.99)
    assert _ids(
        pareto_frontier([token_winner, dollar_winner, quality_winner])
    ) == {"tokens", "dollars", "quality"}


def test_flat_slope_dominates_steep_slope_when_means_equal():
    """ADR 0012 4D Pareto: scaling_slope of cost_dollars is a minimized axis.
    With equal means on the other three axes, the configuration whose cost
    grows shallowly with difficulty dominates the one that cliffs.

    Test values are chosen to sum exactly under IEEE 754 so the means tie
    bit-for-bit (avoid 0.1+0.1+0.1 != 0.01+0.10+0.19 in float).
    """
    flat = _multi_problem_trial(
        "flat",
        per_problem=[(1, 100, 3.0, 0.5), (2, 100, 3.0, 0.5), (3, 100, 3.0, 0.5)],
    )
    steep = _multi_problem_trial(
        "steep",
        per_problem=[(1, 100, 1.0, 0.5), (2, 100, 3.0, 0.5), (3, 100, 5.0, 0.5)],
    )
    assert _ids(pareto_frontier([flat, steep])) == {"flat"}


def test_steep_quality_drop_does_not_affect_pareto_in_v1():
    """v1 ADR 0012: only cost_dollars slope is a Pareto axis; quality slope
    is recorded in the profile but does not enter the dominance rule.
    A trial whose quality degrades steeply but matches on the other axes is
    *not* dominated on that ground alone."""
    flat = _multi_problem_trial(
        "flat_quality",
        per_problem=[(1, 100, 3.0, 0.5), (2, 100, 3.0, 0.5), (3, 100, 3.0, 0.5)],
    )
    cliffy_quality = _multi_problem_trial(
        "cliffy_quality",
        per_problem=[(1, 100, 3.0, 1.0), (2, 100, 3.0, 0.5), (3, 100, 3.0, 0.0)],
    )
    # Both have mean tokens=100, mean dollars=3.0, slope_dollars=0.
    # Means on quality: 0.5 each. Neither dominates the other.
    assert _ids(pareto_frontier([flat, cliffy_quality])) == {
        "flat_quality",
        "cliffy_quality",
    }


def test_trial_without_required_metrics_excluded():
    """A trial whose event stream lacks one of the required Pareto axes
    (tokens_consumed, cost_dollars, quality_score) is excluded — there is
    no signal on a load-bearing dimension."""
    complete = _trial("complete", tokens=100, dollars=0.10, quality=0.5)
    missing_dollars_events = [
        TrialEvent(
            phase="eval",
            timestamp="t",
            payload={"problem_id": "p1", "difficulty": 1, "exit_code": 0},
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
        TrialEvent(
            phase="metric_record",
            timestamp="t",
            payload={
                "problem_id": "p1",
                "metric_name": "quality_score",
                "value": 0.9,
                "n_samples": 1,
            },
        ),
    ]
    incomplete = Trial(
        trial_id="incomplete",
        package=_package(),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="v"),
        version_vector=VersionVector(
            pi_version="0.74.0", package_versions={}, eval_suite_version="v"
        ),
        events=missing_dollars_events,
        outcome="completed",
    )
    assert _ids(pareto_frontier([complete, incomplete])) == {"complete"}


def test_add_to_frontier_incremental_update():
    from pi_evaluator.domain.pareto import add_to_frontier

    frontier = []
    t1 = _trial("t1", tokens=100, dollars=0.1, quality=0.5)
    frontier = add_to_frontier(frontier, t1)
    assert _ids(frontier) == {"t1"}

    # Dominated trial
    t2 = _trial("t2", tokens=200, dollars=0.2, quality=0.4)
    frontier = add_to_frontier(frontier, t2)
    assert _ids(frontier) == {"t1"}

    # Dominating trial
    t3 = _trial("t3", tokens=50, dollars=0.05, quality=0.6)
    frontier = add_to_frontier(frontier, t3)
    assert _ids(frontier) == {"t3"}

    # Non-dominating trial (tradeoff)
    t4 = _trial("t4", tokens=10, dollars=0.5, quality=0.7)
    frontier = add_to_frontier(frontier, t4)
    assert _ids(frontier) == {"t3", "t4"}
