from pi_evaluator.adapters.stub_scorer import StubScorer
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RawTelemetry,
    SubjectiveScore,
    Trial,
    VersionVector,
)
from pi_evaluator.ports.scoring_port import ScoringPort


def _trial() -> Trial:
    return Trial(
        trial_id="t-1",
        package=Package(model="m", system_prompt="", skills=[], template_values={}),
        eval_suite_ref=EvalSuiteRef(suite_id="s", suite_version="1.0"),
        version_vector=VersionVector(
            pi_version="0.1", package_versions={}, eval_suite_version="1.0"
        ),
    )


def test_stub_scorer_satisfies_port_protocol():
    assert isinstance(StubScorer(), ScoringPort)


def test_stub_scorer_default_objective():
    scorer = StubScorer()
    m = scorer.score_objective(RawTelemetry(events=[], exit_code=0))
    assert m == Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0)


def test_stub_scorer_returns_configured_metrics_regardless_of_telemetry():
    fixed = Metrics(tokens_consumed=42, validation_pass_rate=1.0, quality_score=0.7)
    scorer = StubScorer(metrics=fixed)
    a = scorer.score_objective(RawTelemetry(events=[], exit_code=0))
    b = scorer.score_objective(RawTelemetry(events=[{"x": 1}], exit_code=137))
    assert a == fixed and b == fixed


def test_stub_scorer_subjective_default_is_none():
    scorer = StubScorer()
    assert scorer.score_subjective(_trial()) is None


def test_stub_scorer_returns_configured_subjective():
    s = SubjectiveScore(score=4.0, notes="nice", scorer="me", timestamp="t")
    scorer = StubScorer(subjective=s)
    assert scorer.score_subjective(_trial()) is s
