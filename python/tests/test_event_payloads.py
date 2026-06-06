"""Tests for the typed per-phase event-payload model (ADR 0017)."""

from __future__ import annotations

import logging

from pi_evaluator.domain.event_payloads import (
    BoundaryViolation,
    Configured,
    CostCapWarning,
    EvalRecord,
    Finalized,
    MetricRecord,
    parse,
    to_payload,
)
from pi_evaluator.domain.types import Event


def test_parse_metric_record():
    ev = Event(
        phase="metric_record",
        timestamp="t",
        payload={"problem_id": "p1", "metric_name": "cost_dollars", "value": 0.1,
                 "n_samples": 1},
    )
    assert parse(ev) == MetricRecord(
        problem_id="p1", metric_name="cost_dollars", value=0.1, n_samples=1
    )


def test_parse_eval_record():
    ev = Event(
        phase="eval",
        timestamp="t",
        payload={"problem_id": "p1", "difficulty": 3, "exit_code": 0},
    )
    assert parse(ev) == EvalRecord(problem_id="p1", difficulty=3, exit_code=0)


def test_parse_configured_and_finalized_and_warning():
    assert parse(Event("configured", "t", {"package_model": "m"})) == Configured("m")
    assert parse(
        Event("cost_cap_warning", "t", {"scope": "per_trial", "cap_usd": 1.0,
              "cumulative_cost_dollars": 0.9, "fraction": 0.8})
    ) == CostCapWarning("per_trial", 1.0, 0.9, 0.8)
    assert parse(
        Event("finalized", "t", {"tokens_consumed": 5, "cost_dollars": 0.2,
              "validation_pass_rate": 1.0, "quality_score": 0.5,
              "outcome": "completed"})
    ) == Finalized(5, 0.2, 1.0, 0.5, "completed")


def test_parse_boundary_violation_both_shapes():
    timeout = parse(
        Event("boundary_violation", "t", {"reason": "subprocess_timeout",
              "problem_id": "p1", "timeout_seconds": 0.5})
    )
    assert timeout == BoundaryViolation(
        reason="subprocess_timeout", problem_id="p1", timeout_seconds=0.5
    )
    cost = parse(
        Event("boundary_violation", "t", {"reason": "per_trial_cost_cap",
              "cap_usd": 0.1, "cumulative_cost_dollars": 0.2})
    )
    assert cost == BoundaryViolation(
        reason="per_trial_cost_cap", cap_usd=0.1, cumulative_cost_dollars=0.2
    )


def test_parse_unknown_phase_returns_none():
    assert parse(Event("run_started", "t", {"trial_budget": 5})) is None


def test_parse_partial_payload_returns_none():
    """A payload missing a required field is un-projectable, not fatal."""
    assert parse(Event("boundary_violation", "t", {})) is None
    assert parse(Event("metric_record", "t", {"problem_id": "p1"})) is None


def test_parse_drops_unknown_payload_key(caplog):
    """Forward-compat (ADR 0019 D4): a newer-minor field is ignored, not fatal."""
    with caplog.at_level(logging.INFO, logger="pi_evaluator"):
        got = parse(
            Event("eval", "t", {"problem_id": "p1", "difficulty": 1, "exit_code": 0,
                  "future_field": "x"})
        )
    assert got == EvalRecord(problem_id="p1", difficulty=1, exit_code=0)


def test_to_payload_drops_none_optionals():
    """to_payload reproduces the hand-built dicts (no new null keys)."""
    bv = BoundaryViolation(reason="subprocess_timeout", problem_id="p1",
                           timeout_seconds=0.5)
    assert to_payload(bv) == {
        "reason": "subprocess_timeout", "problem_id": "p1", "timeout_seconds": 0.5
    }


def test_to_payload_then_parse_round_trips():
    rec = MetricRecord(problem_id="p1", metric_name="quality_score", value=0.9)
    ev = Event("metric_record", "t", to_payload(rec))
    assert parse(ev) == rec
