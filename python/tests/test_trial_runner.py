from __future__ import annotations

import itertools
import json

import pytest

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.adapters.stub_scorer import StubScorer
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RawTelemetry,
    SubjectiveScore,
    Trial,
    VersionVector,
)
from pi_evaluator.ports.eval_suite_source_port import EvalSuiteSourcePort
from pi_evaluator.trial_runner import TrialRunner


class _ListSuiteSource(EvalSuiteSourcePort):
    def __init__(self, problems: list[GraduatedProblem]) -> None:
        self._problems = problems

    def load(self) -> list[GraduatedProblem]:
        return list(self._problems)


def _problem(pid: str = "p1", difficulty: int = 1) -> GraduatedProblem:
    return GraduatedProblem(
        id=pid,
        title=f"Problem {pid}",
        difficulty=difficulty,
        prompt="solve it",
        workspace_dir=f"/tmp/{pid}",
        validation_steps=[ValidationStep(name="v", command="true")],
        tags=[],
    )


def _package() -> Package:
    return Package(
        model="gemini-flash",
        system_prompt="be precise",
        skills=["lint"],
        template_values={"lang": "python"},
    )


def _suite_ref() -> EvalSuiteRef:
    return EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.4.2",
        package_versions={"lint": "1.0"},
        eval_suite_version="1.0.0",
    )


def _counter_clock(prefix: str = "t"):
    counter = itertools.count()
    return lambda: f"{prefix}{next(counter)}"


def _runner(
    tmp_path,
    *,
    metrics: Metrics | None = None,
    subjective: SubjectiveScore | None = None,
    telemetry: RawTelemetry | None = None,
    problems: list[GraduatedProblem] | None = None,
) -> tuple[TrialRunner, PerTrialDirectoryAdapter]:
    persistence = PerTrialDirectoryAdapter(tmp_path)
    runner = TrialRunner(
        harness=StubAgentHarnessAdapter(telemetry=telemetry),
        scorer=StubScorer(metrics=metrics, subjective=subjective),
        persistence=persistence,
        suite_source=_ListSuiteSource(
            problems if problems is not None else [_problem()]
        ),
        clock=_counter_clock(),
    )
    return runner, persistence


def test_run_trial_returns_trial_with_finalized_metrics(tmp_path):
    fixed = Metrics(tokens_consumed=42, validation_pass_rate=1.0, quality_score=0.7)
    runner, _ = _runner(tmp_path, metrics=fixed)
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert isinstance(trial, Trial)
    assert trial.trial_id == "t-001"
    assert trial.final_metrics == fixed
    assert trial.subjective_score is None


def test_run_trial_emits_full_phase_sequence(tmp_path):
    runner, _ = _runner(tmp_path, problems=[_problem("p1"), _problem("p2", 2)])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    phases = [e.phase for e in trial.events]
    assert phases == [
        "configured",
        "eval",
        "scored_objective",
        "eval",
        "scored_objective",
        "finalized",
    ]


def test_run_trial_writes_complete_on_disk_layout(tmp_path):
    runner, _ = _runner(tmp_path)
    runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    d = tmp_path / "t-001"
    assert (d / "config.json").exists()
    assert (d / "versions.json").exists()
    assert (d / "events.jsonl").exists()
    assert (d / "final.json").exists()


def test_run_trial_events_jsonl_matches_in_memory_events(tmp_path):
    runner, _ = _runner(tmp_path, problems=[_problem("p1"), _problem("p2", 2)])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    lines = (tmp_path / "t-001" / "events.jsonl").read_text().splitlines()
    on_disk_phases = [json.loads(ln)["phase"] for ln in lines]
    in_memory_phases = [e.phase for e in trial.events]
    assert on_disk_phases == in_memory_phases


def test_run_trial_round_trips_via_load_trials(tmp_path):
    fixed = Metrics(tokens_consumed=5, validation_pass_rate=1.0, quality_score=0.9)
    runner, persistence = _runner(tmp_path, metrics=fixed)
    runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    [loaded] = persistence.load_trials()
    assert loaded.trial_id == "t-001"
    assert loaded.final_metrics == fixed
    assert [e.phase for e in loaded.events] == [
        "configured",
        "eval",
        "scored_objective",
        "finalized",
    ]


def test_run_trial_aggregates_metrics_across_problems(tmp_path):
    """With identical per-problem metrics, the aggregate is sum of tokens
    and mean of the rates (mean of identical values = the value)."""
    fixed = Metrics(tokens_consumed=10, validation_pass_rate=0.5, quality_score=0.8)
    runner, _ = _runner(
        tmp_path,
        metrics=fixed,
        problems=[_problem("p1"), _problem("p2"), _problem("p3")],
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.final_metrics is not None
    assert trial.final_metrics.tokens_consumed == 30
    assert trial.final_metrics.validation_pass_rate == pytest.approx(0.5)
    assert trial.final_metrics.quality_score == pytest.approx(0.8)


def test_run_trial_with_empty_suite_emits_only_configured_and_finalized(tmp_path):
    runner, _ = _runner(tmp_path, problems=[])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    phases = [e.phase for e in trial.events]
    assert phases == ["configured", "finalized"]
    assert trial.final_metrics == Metrics(
        tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0
    )


def test_run_trial_default_outcome_is_completed(tmp_path):
    runner, _ = _runner(tmp_path)
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.outcome == "completed"
    finalized = next(e for e in trial.events if e.phase == "finalized")
    assert finalized.payload["outcome"] == "completed"


def test_run_trial_classifies_nonzero_exit_as_error_escalated(tmp_path):
    runner, _ = _runner(
        tmp_path,
        telemetry=RawTelemetry(events=[], exit_code=1),
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.outcome == "error_escalated"


def test_run_trial_classifies_assistant_stop_reason_error_as_error_escalated(tmp_path):
    runner, _ = _runner(
        tmp_path,
        telemetry=RawTelemetry(
            events=[
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "stopReason": "error",
                        "usage": {"totalTokens": 0},
                    },
                }
            ],
            exit_code=0,
        ),
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.outcome == "error_escalated"


def test_run_trial_passes_workspace_to_harness(tmp_path):
    """The harness receives ``problem.workspace_dir`` as its workspace
    argument (Phase 1 placeholder; Phase 2 introduces tmpdir copy)."""
    captured: dict[str, str] = {}

    class _CapturingHarness:
        def run(self, package, problem, workspace):
            captured["workspace"] = workspace
            return RawTelemetry(events=[], exit_code=0)

    runner = TrialRunner(
        harness=_CapturingHarness(),  # type: ignore[arg-type]
        scorer=StubScorer(),
        persistence=PerTrialDirectoryAdapter(tmp_path),
        suite_source=_ListSuiteSource([_problem("p1")]),
        clock=_counter_clock(),
    )
    runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert captured["workspace"] == "/tmp/p1"
