from __future__ import annotations

import pytest
from builders import make_eval_suite_ref, make_version_vector

from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.types import (
    Package,
    RawTelemetry,
    Trial,
    ValidationResult,
)
from pi_evaluator.ports.scoring_port import ScoringPort


def _validation(name: str, *, passed: bool) -> ValidationResult:
    return ValidationResult(
        step_name=name,
        exit_code=0 if passed else 1,
        stdout="",
        stderr="",
        passed=passed,
    )


def _telemetry(
    events: list[dict] | None = None,
    validation_results: list[ValidationResult] | None = None,
    exit_code: int = 0,
) -> RawTelemetry:
    return RawTelemetry(
        events=events or [],
        exit_code=exit_code,
        validation_results=validation_results or [],
    )


def _trial() -> Trial:
    return Trial(
        trial_id="t-1",
        package=Package(
            model="google/gemini-2.5-flash",
            system_prompt="",
            skills=[],
            template_values={},
        ),
        eval_suite_ref=make_eval_suite_ref(suite_id="s", suite_version="1.0"),
        version_vector=make_version_vector(
            pi_version="0.73", package_versions={}, eval_suite_version="1.0"
        ),
    )


def test_scorer_satisfies_port_protocol():
    assert isinstance(SyntheticSuiteScorer(), ScoringPort)


def test_tokens_consumed_sums_assistant_message_end_usage():
    events = [
        {"type": "session", "id": "s"},
        {"type": "agent_start"},
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 100}},
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 250}},
        },
        {"type": "agent_end"},
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.tokens_consumed == 350


def test_tokens_consumed_zero_when_no_message_end_events():
    events = [{"type": "agent_start"}, {"type": "agent_end"}]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.tokens_consumed == 0


def test_tokens_consumed_skips_non_assistant_messages():
    events = [
        {
            "type": "message_end",
            "message": {"role": "user", "usage": {"totalTokens": 999}},
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 50}},
        },
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.tokens_consumed == 50


def test_cost_dollars_sums_assistant_message_end_cost_total():
    events = [
        {"type": "session", "id": "s"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "usage": {
                    "totalTokens": 100,
                    "cost": {
                        "input": 0.001,
                        "output": 0.002,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "total": 0.003,
                    },
                },
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "usage": {"totalTokens": 50, "cost": {"total": 0.0015}},
            },
        },
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.cost_dollars == pytest.approx(0.0045)


def test_cost_dollars_zero_when_cost_field_missing():
    events = [
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 100}},
        },
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.cost_dollars == 0.0


def test_cost_dollars_skips_non_assistant_messages():
    events = [
        {
            "type": "message_end",
            "message": {
                "role": "user",
                "usage": {"cost": {"total": 0.999}},
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "usage": {"cost": {"total": 0.005}},
            },
        },
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.cost_dollars == pytest.approx(0.005)


def test_tokens_consumed_handles_missing_usage_gracefully():
    events = [
        {"type": "message_end", "message": {"role": "assistant"}},
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 7}},
        },
    ]
    metrics = SyntheticSuiteScorer().score_objective(_telemetry(events=events))
    assert metrics.tokens_consumed == 7


def test_validation_pass_rate_full_pass():
    results = [
        _validation("a", passed=True),
        _validation("b", passed=True),
        _validation("c", passed=True),
    ]
    metrics = SyntheticSuiteScorer().score_objective(
        _telemetry(validation_results=results)
    )
    assert metrics.validation_pass_rate == 1.0


def test_validation_pass_rate_full_fail():
    results = [_validation("a", passed=False), _validation("b", passed=False)]
    metrics = SyntheticSuiteScorer().score_objective(
        _telemetry(validation_results=results)
    )
    assert metrics.validation_pass_rate == 0.0


def test_validation_pass_rate_mixed():
    results = [
        _validation("a", passed=True),
        _validation("b", passed=False),
        _validation("c", passed=True),
    ]
    metrics = SyntheticSuiteScorer().score_objective(
        _telemetry(validation_results=results)
    )
    assert metrics.validation_pass_rate == pytest.approx(2 / 3)


def test_validation_pass_rate_no_results_is_zero_no_signal():
    metrics = SyntheticSuiteScorer().score_objective(_telemetry())
    assert metrics.validation_pass_rate == 0.0


def test_quality_score_equals_validation_pass_rate_in_v1():
    results = [_validation("a", passed=True), _validation("b", passed=False)]
    metrics = SyntheticSuiteScorer().score_objective(
        _telemetry(validation_results=results)
    )
    assert metrics.quality_score == pytest.approx(metrics.validation_pass_rate)


def test_score_subjective_always_none_in_v1():
    assert SyntheticSuiteScorer().score_subjective(_trial()) is None


def test_full_telemetry_to_metrics():
    events = [
        {
            "type": "message_end",
            "message": {"role": "assistant", "usage": {"totalTokens": 1234}},
        },
    ]
    results = [
        _validation("a", passed=True),
        _validation("b", passed=False),
    ]
    metrics = SyntheticSuiteScorer().score_objective(
        _telemetry(events=events, validation_results=results)
    )
    assert metrics.tokens_consumed == 1234
    assert metrics.validation_pass_rate == pytest.approx(0.5)
    assert metrics.quality_score == pytest.approx(0.5)
