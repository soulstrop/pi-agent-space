from __future__ import annotations

import itertools
import json
import subprocess

import pytest
from builders import make_eval_suite_ref, make_version_vector

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
    return make_eval_suite_ref(suite_id="coding_v1", suite_version="1.0.0")


def _versions() -> VersionVector:
    return make_version_vector(
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
    """ADR 0012: each problem emits one `eval` followed by N `metric_record`
    events (one per metric_name in v1: tokens_consumed, cost_dollars,
    validation_pass_rate, quality_score)."""
    runner, _ = _runner(tmp_path, problems=[_problem("p1"), _problem("p2", 2)])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    phases = [e.phase for e in trial.events]
    per_problem = ["eval"] + ["metric_record"] * 4
    assert phases == ["configured"] + per_problem * 2 + ["finalized"]


def test_run_trial_emits_metric_record_event_per_metric_per_problem(tmp_path):
    """ADR 0012: payload shape is {problem_id, metric_name, value, n_samples};
    n_samples=1 in v1 (no replication yet, ADR 0006)."""
    fixed = Metrics(
        tokens_consumed=42,
        validation_pass_rate=0.5,
        quality_score=0.7,
        cost_dollars=0.013,
    )
    runner, _ = _runner(tmp_path, metrics=fixed, problems=[_problem("p1")])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    records = [e for e in trial.events if e.phase == "metric_record"]
    by_metric = {e.payload["metric_name"]: e.payload for e in records}
    assert set(by_metric) == {
        "tokens_consumed",
        "cost_dollars",
        "validation_pass_rate",
        "quality_score",
    }
    assert by_metric["tokens_consumed"] == {
        "problem_id": "p1",
        "metric_name": "tokens_consumed",
        "value": 42,
        "n_samples": 1,
    }
    assert by_metric["cost_dollars"]["value"] == pytest.approx(0.013)
    assert by_metric["validation_pass_rate"]["value"] == pytest.approx(0.5)
    assert by_metric["quality_score"]["value"] == pytest.approx(0.7)
    assert all(p["n_samples"] == 1 for p in by_metric.values())


def test_run_trial_no_longer_emits_scored_objective(tmp_path):
    """ADR 0012 supersedes scored_objective with metric_record events."""
    runner, _ = _runner(tmp_path, problems=[_problem("p1"), _problem("p2", 2)])
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert all(e.phase != "scored_objective" for e in trial.events)


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
        "metric_record",
        "metric_record",
        "metric_record",
        "metric_record",
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


class _PerProblemScorer:
    """Returns objective metrics from a per-problem queue.

    Lets cost-cap tests drive accumulated cost across problems
    deterministically without relying on telemetry shape.
    """

    def __init__(self, metrics: list[Metrics]) -> None:
        self._queue = list(metrics)

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        return self._queue.pop(0)

    def score_subjective(self, trial) -> SubjectiveScore | None:
        return None


def _per_problem_runner(
    tmp_path,
    *,
    per_problem_metrics: list[Metrics],
    n_problems: int,
) -> tuple[TrialRunner, PerTrialDirectoryAdapter]:
    persistence = PerTrialDirectoryAdapter(tmp_path)
    runner = TrialRunner(
        harness=StubAgentHarnessAdapter(),
        scorer=_PerProblemScorer(per_problem_metrics),
        persistence=persistence,
        suite_source=_ListSuiteSource(
            [_problem(f"p{i + 1}") for i in range(n_problems)]
        ),
        clock=_counter_clock(),
    )
    return runner, persistence


def test_per_trial_cost_cap_none_disables_check(tmp_path):
    """cap=None → no warning, no boundary, regardless of cost."""
    runner, _ = _per_problem_runner(
        tmp_path,
        per_problem_metrics=[
            Metrics(
                tokens_consumed=10,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=100.0,
            )
        ],
        n_problems=1,
    )
    trial = runner.run_trial(
        "t-001",
        _package(),
        _suite_ref(),
        _versions(),
        per_trial_cost_cap_usd=None,
    )
    assert trial.outcome == "completed"
    phases = [e.phase for e in trial.events]
    assert "cost_cap_warning" not in phases
    assert "boundary_violation" not in phases


def test_per_trial_cost_cap_emits_warning_event_when_crossed(tmp_path):
    """Cost between warning fraction × cap and cap → warning, normal close."""
    runner, _ = _per_problem_runner(
        tmp_path,
        per_problem_metrics=[
            Metrics(
                tokens_consumed=10,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.09,  # > 0.8 * 0.10 but < 0.10
            )
        ],
        n_problems=1,
    )
    trial = runner.run_trial(
        "t-001",
        _package(),
        _suite_ref(),
        _versions(),
        per_trial_cost_cap_usd=0.10,
    )
    assert trial.outcome == "completed"
    phases = [e.phase for e in trial.events]
    assert phases.count("cost_cap_warning") == 1
    assert "boundary_violation" not in phases
    warning = next(e for e in trial.events if e.phase == "cost_cap_warning")
    assert warning.payload["scope"] == "per_trial"
    assert warning.payload["cap_usd"] == 0.10


def test_per_trial_cost_cap_hard_stop_produces_boundary_violation(tmp_path):
    """Cost above cap → boundary_violation event, outcome, zeroed quality."""
    runner, _ = _per_problem_runner(
        tmp_path,
        per_problem_metrics=[
            Metrics(
                tokens_consumed=10,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.20,  # > 0.10 cap
            )
        ],
        n_problems=1,
    )
    trial = runner.run_trial(
        "t-001",
        _package(),
        _suite_ref(),
        _versions(),
        per_trial_cost_cap_usd=0.10,
    )
    assert trial.outcome == "boundary_violation"
    phases = [e.phase for e in trial.events]
    assert "boundary_violation" in phases
    assert phases[-1] == "finalized"
    assert trial.final_metrics is not None
    assert trial.final_metrics.cost_dollars == pytest.approx(0.20)
    assert trial.final_metrics.tokens_consumed == 10
    assert trial.final_metrics.validation_pass_rate == 0.0
    assert trial.final_metrics.quality_score == 0.0
    finalized = next(e for e in trial.events if e.phase == "finalized")
    assert finalized.payload["outcome"] == "boundary_violation"
    boundary = next(e for e in trial.events if e.phase == "boundary_violation")
    assert boundary.payload["reason"] == "per_trial_cost_cap"
    assert boundary.payload["cap_usd"] == 0.10
    assert boundary.payload["cumulative_cost_dollars"] == pytest.approx(0.20)


def test_per_trial_cost_cap_stops_running_remaining_problems(tmp_path):
    """Three problems, cap tripped after p2 → p3 never runs."""
    runner, _ = _per_problem_runner(
        tmp_path,
        per_problem_metrics=[
            Metrics(
                tokens_consumed=5,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.04,
            ),
            Metrics(
                tokens_consumed=5,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.08,  # cumulative 0.12 > 0.10
            ),
            Metrics(
                tokens_consumed=5,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.04,  # should never be scored
            ),
        ],
        n_problems=3,
    )
    trial = runner.run_trial(
        "t-001",
        _package(),
        _suite_ref(),
        _versions(),
        per_trial_cost_cap_usd=0.10,
    )
    assert trial.outcome == "boundary_violation"
    eval_events = [e for e in trial.events if e.phase == "eval"]
    assert len(eval_events) == 2
    assert trial.final_metrics is not None
    assert trial.final_metrics.cost_dollars == pytest.approx(0.12)
    assert trial.final_metrics.tokens_consumed == 10


def test_per_trial_cost_cap_warning_emitted_at_most_once(tmp_path):
    """Two problems above warning fraction → warning fires only on first crossing."""
    runner, _ = _per_problem_runner(
        tmp_path,
        per_problem_metrics=[
            Metrics(
                tokens_consumed=5,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.085,  # crosses warning at 0.08
            ),
            Metrics(
                tokens_consumed=5,
                validation_pass_rate=1.0,
                quality_score=1.0,
                cost_dollars=0.005,  # cumulative 0.09, still under cap
            ),
        ],
        n_problems=2,
    )
    trial = runner.run_trial(
        "t-001",
        _package(),
        _suite_ref(),
        _versions(),
        per_trial_cost_cap_usd=0.10,
    )
    assert trial.outcome == "completed"
    phases = [e.phase for e in trial.events]
    assert phases.count("cost_cap_warning") == 1


# --- ADR 0007 A2 + ADR 0011: subprocess timeout → boundary_violation ---


class _TimeoutOnNthHarness:
    """Harness that raises subprocess.TimeoutExpired on the Nth call.

    Earlier calls return a clean RawTelemetry; later calls (after the
    timeout) should never happen because the loop breaks. Asserting on
    ``self.calls`` confirms the runner stopped scheduling problems.
    """

    def __init__(self, timeout_on_call: int, timeout_seconds: float = 0.05) -> None:
        self._timeout_on_call = timeout_on_call
        self._timeout_seconds = timeout_seconds
        self.calls = 0

    def run(self, package, problem, workspace):
        self.calls += 1
        if self.calls == self._timeout_on_call:
            raise subprocess.TimeoutExpired(cmd="pi", timeout=self._timeout_seconds)
        return RawTelemetry(events=[], exit_code=0)


def test_harness_timeout_emits_boundary_violation_event(tmp_path):
    """A subprocess.TimeoutExpired from the harness produces a
    boundary_violation event with reason='subprocess_timeout', and the
    classifier resolves outcome accordingly."""
    harness = _TimeoutOnNthHarness(timeout_on_call=1, timeout_seconds=0.5)
    runner = TrialRunner(
        harness=harness,  # type: ignore[arg-type]
        scorer=StubScorer(),
        persistence=PerTrialDirectoryAdapter(tmp_path),
        suite_source=_ListSuiteSource([_problem("p1")]),
        clock=_counter_clock(),
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.outcome == "boundary_violation"
    phases = [e.phase for e in trial.events]
    assert "boundary_violation" in phases
    assert phases[-1] == "finalized"
    boundary = next(e for e in trial.events if e.phase == "boundary_violation")
    assert boundary.payload["reason"] == "subprocess_timeout"
    assert boundary.payload["problem_id"] == "p1"
    assert boundary.payload["timeout_seconds"] == 0.5
    finalized = next(e for e in trial.events if e.phase == "finalized")
    assert finalized.payload["outcome"] == "boundary_violation"


def test_harness_timeout_zeroes_quality_and_pass_rate(tmp_path):
    """Boundary-violated trials carry zeroed quality / pass-rate per ADR
    0011's outcome-driven metric shape."""
    harness = _TimeoutOnNthHarness(timeout_on_call=1)
    runner = TrialRunner(
        harness=harness,  # type: ignore[arg-type]
        scorer=StubScorer(),
        persistence=PerTrialDirectoryAdapter(tmp_path),
        suite_source=_ListSuiteSource([_problem("p1")]),
        clock=_counter_clock(),
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert trial.final_metrics is not None
    assert trial.final_metrics.quality_score == 0.0
    assert trial.final_metrics.validation_pass_rate == 0.0


def test_harness_timeout_mid_loop_skips_remaining_problems(tmp_path):
    """Three problems, second times out → third never runs, first's
    eval/scored events are preserved."""
    harness = _TimeoutOnNthHarness(timeout_on_call=2)
    runner = TrialRunner(
        harness=harness,  # type: ignore[arg-type]
        scorer=StubScorer(),
        persistence=PerTrialDirectoryAdapter(tmp_path),
        suite_source=_ListSuiteSource(
            [_problem("p1"), _problem("p2"), _problem("p3")]
        ),
        clock=_counter_clock(),
    )
    trial = runner.run_trial("t-001", _package(), _suite_ref(), _versions())
    assert harness.calls == 2, "third problem must not be scheduled after timeout"
    assert trial.outcome == "boundary_violation"
    evals = [e for e in trial.events if e.phase == "eval"]
    assert [e.payload["problem_id"] for e in evals] == ["p1"]


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
