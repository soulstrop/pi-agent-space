"""Tests for Phase 2.3: validation execution after Pi exits."""

from __future__ import annotations

import stat
from pathlib import Path

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import Package, RawTelemetry, ValidationResult


def _make_mock_pi(tmp_path: Path) -> str:
    script = tmp_path / "mock_pi"
    script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _package() -> Package:
    return Package(
        model="google/gemini-2.5-flash",
        system_prompt="",
        skills=[],
        template_values={},
    )


def _problem(workspace: Path, steps: list[ValidationStep]) -> GraduatedProblem:
    return GraduatedProblem(
        id="p",
        title="t",
        difficulty=1,
        prompt="prompt",
        workspace_dir=str(workspace),
        validation_steps=steps,
        tags=[],
    )


def test_validation_result_dataclass_holds_fields():
    r = ValidationResult(
        step_name="run pytest",
        exit_code=0,
        stdout="ok",
        stderr="",
        passed=True,
    )
    assert r.step_name == "run pytest"
    assert r.passed


def test_raw_telemetry_defaults_validation_results_to_empty_list():
    t = RawTelemetry(events=[], exit_code=0)
    assert t.validation_results == []


def test_raw_telemetry_carries_validation_results():
    r = ValidationResult(step_name="v", exit_code=0, stdout="", stderr="", passed=True)
    t = RawTelemetry(events=[], exit_code=0, validation_results=[r])
    assert t.validation_results == [r]


def test_adapter_runs_validation_after_pi_exits(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(
        src,
        [
            ValidationStep(name="trivial", command="true", expected_exit_code=0),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    assert len(result.validation_results) == 1
    v = result.validation_results[0]
    assert v.step_name == "trivial"
    assert v.exit_code == 0
    assert v.passed


def test_validation_failure_when_exit_code_unexpected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(
        src,
        [
            ValidationStep(name="should-pass", command="false", expected_exit_code=0),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    [v] = result.validation_results
    assert v.exit_code == 1
    assert not v.passed


def test_validation_passes_when_nonzero_exit_was_expected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(
        src,
        [
            ValidationStep(name="must-fail", command="false", expected_exit_code=1),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    [v] = result.validation_results
    assert v.passed


def test_multiple_validation_steps_run_in_declared_order(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(
        src,
        [
            ValidationStep(name="a", command="echo aaa"),
            ValidationStep(name="b", command="echo bbb"),
            ValidationStep(name="c", command="echo ccc"),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    assert [v.step_name for v in result.validation_results] == ["a", "b", "c"]
    assert all(v.passed for v in result.validation_results)
    assert result.validation_results[0].stdout.strip() == "aaa"


def test_validation_runs_in_materialized_workspace_not_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "marker.txt").write_text("here")
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(
        src,
        [
            ValidationStep(name="check", command="cat marker.txt"),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    [v] = result.validation_results
    assert v.passed
    assert v.stdout.strip() == "here"


def test_validation_runs_even_when_pi_fails(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    failing_pi = tmp_path / "mock_pi"
    failing_pi.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(99)\n")
    failing_pi.chmod(
        failing_pi.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    adapter = CliSubprocessAdapter(pi_binary=str(failing_pi))
    problem = _problem(
        src,
        [
            ValidationStep(name="still-runs", command="true"),
        ],
    )
    result = adapter.run(_package(), problem, workspace=str(src))
    assert result.exit_code == 99
    [v] = result.validation_results
    assert v.passed


def test_problem_with_no_validation_steps_yields_empty_validation_results(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pi = _make_mock_pi(tmp_path)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    problem = _problem(src, [])
    result = adapter.run(_package(), problem, workspace=str(src))
    assert result.validation_results == []
