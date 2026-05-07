from dataclasses import FrozenInstanceError

import pytest

from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    SubjectiveScore,
    Trial,
    TrialEvent,
    VersionVector,
)


def _pkg():
    return Package(
        model="gemini-flash",
        system_prompt="You are a coder.",
        skills=["lint", "format"],
        template_values={"lang": "python"},
    )


def _suite():
    return EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0")


def _versions():
    return VersionVector(
        pi_version="0.4.2",
        package_versions={"lint": "1.0"},
        eval_suite_version="1.0.0",
    )


def test_package_holds_fields():
    p = _pkg()
    assert p.model == "gemini-flash"
    assert p.skills == ["lint", "format"]
    assert p.template_values == {"lang": "python"}


def test_package_is_frozen():
    p = _pkg()
    with pytest.raises(FrozenInstanceError):
        p.model = "claude"  # type: ignore[misc]


def test_metrics_holds_fields():
    m = Metrics(tokens_consumed=100, validation_pass_rate=0.5, quality_score=0.8)
    assert m.tokens_consumed == 100
    assert m.validation_pass_rate == 0.5
    assert m.quality_score == 0.8


def test_metrics_is_frozen():
    m = Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0)
    with pytest.raises(FrozenInstanceError):
        m.tokens_consumed = 999  # type: ignore[misc]


def test_subjective_score_holds_fields():
    s = SubjectiveScore(
        score=4.0, notes="ok", scorer="user@x", timestamp="2026-01-01T00:00:00Z"
    )
    assert s.score == 4.0
    assert s.scorer == "user@x"


def test_eval_suite_ref_holds_fields():
    r = _suite()
    assert r.suite_id == "coding_v1"
    assert r.suite_version == "1.0.0"


def test_version_vector_holds_fields():
    v = _versions()
    assert v.pi_version == "0.4.2"
    assert v.package_versions == {"lint": "1.0"}
    assert v.eval_suite_version == "1.0.0"


def test_trial_event_with_explicit_payload():
    e = TrialEvent(phase="finalized", timestamp="t", payload={"score": 1.0})
    assert e.payload == {"score": 1.0}


def test_trial_event_default_payload_is_independent():
    e1 = TrialEvent(phase="configured", timestamp="t1")
    e2 = TrialEvent(phase="eval", timestamp="t2")
    e1.payload["k"] = "v"
    assert "k" not in e2.payload


def test_trial_constructs_with_empty_event_list_and_no_scores():
    t = Trial(
        trial_id="t-001",
        package=_pkg(),
        eval_suite_ref=_suite(),
        version_vector=_versions(),
    )
    assert t.events == []
    assert t.final_metrics is None
    assert t.subjective_score is None


def test_trial_default_events_is_independent():
    t1 = Trial(
        trial_id="a",
        package=_pkg(),
        eval_suite_ref=_suite(),
        version_vector=_versions(),
    )
    t2 = Trial(
        trial_id="b",
        package=_pkg(),
        eval_suite_ref=_suite(),
        version_vector=_versions(),
    )
    t1.events.append(TrialEvent(phase="configured", timestamp="t"))
    assert t2.events == []


def test_trial_accumulates_events_and_finalizes():
    t = Trial(
        trial_id="t-001",
        package=_pkg(),
        eval_suite_ref=_suite(),
        version_vector=_versions(),
    )
    t.events.append(TrialEvent(phase="configured", timestamp="t1"))
    t.events.append(TrialEvent(phase="eval", timestamp="t2"))
    t.final_metrics = Metrics(
        tokens_consumed=1, validation_pass_rate=1.0, quality_score=1.0
    )
    t.subjective_score = SubjectiveScore(
        score=4.0, notes="", scorer="me", timestamp="t3"
    )
    assert len(t.events) == 2
    assert t.final_metrics.tokens_consumed == 1
    assert t.subjective_score.score == 4.0
