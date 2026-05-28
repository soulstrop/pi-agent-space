"""Tests for the real Pi CLI adapter, using a mock Pi script per test."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import Package, RawTelemetry
from pi_evaluator.ports.agent_harness_port import AgentHarnessPort


def _make_mock_pi(
    tmp_path: Path,
    *,
    stdout_lines: list[str] | None = None,
    stderr_text: str = "",
    exit_code: int = 0,
    log_invocation: Path | None = None,
    sleep_seconds: float = 0.0,
) -> str:
    """Write a tiny Python script that mimics Pi for one test invocation.

    Optional ``log_invocation`` path receives a JSON dump of argv + cwd
    when the mock runs; tests inspect this to verify the adapter built
    the command correctly.

    ``sleep_seconds`` inserts a sleep after stdout is written but before
    exit — used by timeout tests that need the subprocess to outlive a
    short ``subprocess_timeout_seconds`` value.
    """
    script = tmp_path / "mock_pi"
    parts = ["#!/usr/bin/env python3", "import json, os, sys, time"]
    if log_invocation is not None:
        parts.append(f"with open({str(log_invocation)!r}, 'w') as f:")
        parts.append("    json.dump({'argv': sys.argv, 'cwd': os.getcwd()}, f)")
    for line in stdout_lines or []:
        parts.append(f"print({line!r}, flush=True)")
    if stderr_text:
        parts.append(f"sys.stderr.write({stderr_text!r})")
    if sleep_seconds > 0:
        parts.append(f"time.sleep({sleep_seconds})")
    parts.append(f"sys.exit({exit_code})")
    script.write_text("\n".join(parts) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _make_counting_mock_pi(
    tmp_path: Path,
    attempts: list[dict],
    counter_path: Path | None = None,
    cwd_log: Path | None = None,
) -> str:
    """Mock Pi that returns different output across invocations.

    Each ``attempts`` entry shapes one call: ``{"exit_code": int,
    "stdout_lines": list[str]}``. Uses ``counter_path`` (default
    ``tmp_path/counter``) to track invocation count across processes.
    Optional ``cwd_log`` appends each call's cwd so tests can verify
    the same materialized workspace is reused across retries.
    """
    if counter_path is None:
        counter_path = tmp_path / "mock_pi_counter"
    script = tmp_path / "mock_pi"
    encoded = json.dumps(attempts)
    parts = [
        "#!/usr/bin/env python3",
        "import json, os, sys, pathlib",
        f"counter_path = pathlib.Path({str(counter_path)!r})",
        f"attempts = json.loads({encoded!r})",
        "n = int(counter_path.read_text()) if counter_path.exists() else 0",
        "counter_path.write_text(str(n + 1))",
        "idx = min(n, len(attempts) - 1)",
        "attempt = attempts[idx]",
    ]
    if cwd_log is not None:
        parts.append(f"with open({str(cwd_log)!r}, 'a') as f:")
        parts.append("    f.write(os.getcwd() + chr(10))")
    parts.extend(
        [
            "for line in attempt.get('stdout_lines', []):",
            "    print(line, flush=True)",
            "sys.exit(attempt['exit_code'])",
        ]
    )
    script.write_text("\n".join(parts) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _problem(workspace: Path, prompt: str = "solve it") -> GraduatedProblem:
    return GraduatedProblem(
        id="p1",
        title="Test",
        difficulty=1,
        prompt=prompt,
        workspace_dir=str(workspace),
        validation_steps=[ValidationStep(name="v", command="true")],
        tags=[],
    )


def _package(
    model: str = "google/gemini-2.5-flash",
    system_prompt: str = "be concise",
    skills: list[str] | None = None,
) -> Package:
    return Package(
        model=model,
        system_prompt=system_prompt,
        skills=skills if skills is not None else ["read", "write"],
        template_values={},
    )


def _src_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    return src


def test_adapter_satisfies_port_protocol(tmp_path):
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=0)
    assert isinstance(CliSubprocessAdapter(pi_binary=pi), AgentHarnessPort)


def test_parses_json_event_stream(tmp_path):
    src = _src_workspace(tmp_path)
    events = [
        '{"type":"session","version":3,"id":"abc"}',
        '{"type":"agent_start"}',
        '{"type":"message_end","message":{"role":"assistant","usage":{"totalTokens":100}}}',
        '{"type":"agent_end"}',
    ]
    pi = _make_mock_pi(tmp_path, stdout_lines=events, exit_code=0)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert isinstance(result, RawTelemetry)
    assert [e["type"] for e in result.events] == [
        "session",
        "agent_start",
        "message_end",
        "agent_end",
    ]
    assert result.events[2]["message"]["usage"]["totalTokens"] == 100
    assert result.exit_code == 0


def test_captures_nonzero_exit_code(tmp_path):
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=42)
    adapter = CliSubprocessAdapter(pi_binary=pi, retry_budget=0)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 42


def test_preserves_non_json_lines_as_malformed(tmp_path):
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(
        tmp_path,
        stdout_lines=[
            '{"type":"session"}',
            "No API key found for google.",
            '{"type":"agent_end"}',
        ],
    )
    adapter = CliSubprocessAdapter(pi_binary=pi)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert [e["type"] for e in result.events] == ["session", "agent_end"]
    assert result.malformed_lines == ["No API key found for google."]


def test_captures_stderr(tmp_path):
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(
        tmp_path,
        stdout_lines=[],
        stderr_text="pi: failed to launch provider\n",
        exit_code=1,
    )
    adapter = CliSubprocessAdapter(pi_binary=pi, retry_budget=0)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert "failed to launch provider" in result.stderr
    assert result.exit_code == 1


def test_passes_expected_flags_in_argv(tmp_path):
    src = _src_workspace(tmp_path)
    log = tmp_path / "args.json"
    pi = _make_mock_pi(tmp_path, stdout_lines=[], log_invocation=log)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    adapter.run(
        _package(
            model="google/gemini-2.5-flash",
            system_prompt="be terse",
            skills=["read", "bash"],
        ),
        _problem(src, prompt="implement binary search"),
        workspace=str(src),
    )
    argv = json.loads(log.read_text())["argv"]
    assert "--print" in argv
    assert "--no-session" in argv
    assert argv[argv.index("--mode") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "google/gemini-2.5-flash"
    assert argv[argv.index("--system-prompt") + 1] == "be terse"
    assert argv[argv.index("--tools") + 1] == "read,bash"
    assert argv[-1] == "implement binary search"


def test_materializes_workspace_before_running(tmp_path):
    src = _src_workspace(tmp_path)
    (src / "marker.txt").write_text("original")
    log = tmp_path / "inv.json"
    pi = _make_mock_pi(tmp_path, stdout_lines=[], log_invocation=log)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    adapter.run(_package(), _problem(src), workspace=str(src))
    inv = json.loads(log.read_text())
    cwd = Path(inv["cwd"])
    assert cwd != src
    assert (cwd / "marker.txt").read_text() == "original"


def test_omits_optional_flags_when_unset(tmp_path):
    """An empty system_prompt or skills list should not produce empty
    flag values that would confuse Pi."""
    src = _src_workspace(tmp_path)
    log = tmp_path / "args.json"
    pi = _make_mock_pi(tmp_path, stdout_lines=[], log_invocation=log)
    adapter = CliSubprocessAdapter(pi_binary=pi)
    adapter.run(
        Package(
            model="google/gemini-2.5-flash",
            system_prompt="",
            skills=[],
            template_values={},
        ),
        _problem(src),
        workspace=str(src),
    )
    argv = json.loads(log.read_text())["argv"]
    assert "--system-prompt" not in argv
    assert "--tools" not in argv


def test_default_retry_budget_is_two(tmp_path):
    """ADR 0007 commits to N=2 retries as the default. Persistent failure
    across (1 initial + 2 retries) = 3 attempts."""
    src = _src_workspace(tmp_path)
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[{"exit_code": 1, "stdout_lines": []}] * 5,
    )
    sleeps: list[float] = []
    adapter = CliSubprocessAdapter(pi_binary=pi, sleep=sleeps.append)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert int((tmp_path / "mock_pi_counter").read_text()) == 3
    assert result.exit_code == 1
    assert len(sleeps) == 2  # backoff before retry 1 and retry 2


def test_retries_on_nonzero_exit_until_success(tmp_path):
    src = _src_workspace(tmp_path)
    success_events = [
        '{"type":"message_end","message":{"role":"assistant",'
        '"usage":{"totalTokens":42}}}',
    ]
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[
            {"exit_code": 1, "stdout_lines": []},
            {"exit_code": 0, "stdout_lines": success_events},
        ],
    )
    sleeps: list[float] = []
    adapter = CliSubprocessAdapter(pi_binary=pi, retry_budget=2, sleep=sleeps.append)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 0
    assert int((tmp_path / "mock_pi_counter").read_text()) == 2
    assert len(sleeps) == 1


def test_returns_last_failure_after_retry_budget_exhausted(tmp_path):
    src = _src_workspace(tmp_path)
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[{"exit_code": 7, "stdout_lines": []}] * 5,
    )
    adapter = CliSubprocessAdapter(
        pi_binary=pi, retry_budget=2, sleep=lambda _s: None
    )
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 7
    assert int((tmp_path / "mock_pi_counter").read_text()) == 3


def test_retries_on_assistant_stop_reason_error(tmp_path):
    """stopReason=='error' on assistant message_end is treated as a
    retryable transient even when subprocess exit is clean."""
    src = _src_workspace(tmp_path)
    error_events = [
        '{"type":"message_end","message":{"role":"assistant",'
        '"stopReason":"error","usage":{"totalTokens":0}}}',
    ]
    success_events = [
        '{"type":"message_end","message":{"role":"assistant",'
        '"usage":{"totalTokens":10}}}',
    ]
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[
            {"exit_code": 0, "stdout_lines": error_events},
            {"exit_code": 0, "stdout_lines": success_events},
        ],
    )
    adapter = CliSubprocessAdapter(
        pi_binary=pi, retry_budget=2, sleep=lambda _s: None
    )
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert result.exit_code == 0
    assert int((tmp_path / "mock_pi_counter").read_text()) == 2
    assert result.events[0]["message"].get("stopReason") != "error"


def test_no_retry_on_clean_success(tmp_path):
    src = _src_workspace(tmp_path)
    success_events = [
        '{"type":"message_end","message":{"role":"assistant",'
        '"usage":{"totalTokens":5}}}',
    ]
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[{"exit_code": 0, "stdout_lines": success_events}],
    )
    sleeps: list[float] = []
    adapter = CliSubprocessAdapter(pi_binary=pi, retry_budget=2, sleep=sleeps.append)
    adapter.run(_package(), _problem(src), workspace=str(src))
    assert int((tmp_path / "mock_pi_counter").read_text()) == 1
    assert sleeps == []


def test_retries_use_same_materialized_workspace(tmp_path):
    """ADR 0007 B1 commits to retrying against the same materialized
    workspace — preserves any state Pi started building."""
    src = _src_workspace(tmp_path)
    cwd_log = tmp_path / "cwd_log.txt"
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[{"exit_code": 1, "stdout_lines": []}] * 3,
        cwd_log=cwd_log,
    )
    adapter = CliSubprocessAdapter(
        pi_binary=pi, retry_budget=2, sleep=lambda _s: None
    )
    adapter.run(_package(), _problem(src), workspace=str(src))
    cwds = [ln for ln in cwd_log.read_text().splitlines() if ln]
    assert len(cwds) == 3
    assert cwds[0] == cwds[1] == cwds[2]
    assert Path(cwds[0]) != src


def test_backoff_schedule_passed_to_sleep(tmp_path):
    """Backoff values from the configured schedule pass through to sleep."""
    src = _src_workspace(tmp_path)
    pi = _make_counting_mock_pi(
        tmp_path,
        attempts=[{"exit_code": 1, "stdout_lines": []}] * 5,
    )
    sleeps: list[float] = []
    adapter = CliSubprocessAdapter(
        pi_binary=pi,
        retry_budget=2,
        backoff_seconds=(0.1, 0.2),
        sleep=sleeps.append,
    )
    adapter.run(_package(), _problem(src), workspace=str(src))
    assert sleeps == [0.1, 0.2]


# --- ADR 0007 A2: subprocess timeout ---


def test_no_timeout_kwarg_is_default(tmp_path):
    """Default behavior (no subprocess_timeout_seconds) does not enforce a
    wall-clock limit — preserves the pre-timeout adapter contract."""
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=0)
    adapter = CliSubprocessAdapter(pi_binary=pi, retry_budget=0)
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert isinstance(result, RawTelemetry)
    assert result.exit_code == 0


def test_completion_under_timeout_returns_normal_telemetry(tmp_path):
    """A subprocess that finishes well under the timeout returns RawTelemetry
    unchanged — timeout config is non-disruptive to fast completions."""
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=0)
    adapter = CliSubprocessAdapter(
        pi_binary=pi,
        retry_budget=0,
        subprocess_timeout_seconds=10.0,
    )
    result = adapter.run(_package(), _problem(src), workspace=str(src))
    assert isinstance(result, RawTelemetry)
    assert result.exit_code == 0


def test_timeout_fires_raises_subprocess_timeout_expired(tmp_path):
    """Subprocess outliving the timeout raises subprocess.TimeoutExpired —
    surfaced distinctly from a non-zero exit code (which would return a
    RawTelemetry with exit_code != 0) per ADR 0007 A2."""
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=0, sleep_seconds=1.0)
    adapter = CliSubprocessAdapter(
        pi_binary=pi,
        retry_budget=0,
        subprocess_timeout_seconds=0.05,
    )
    with pytest.raises(subprocess.TimeoutExpired):
        adapter.run(_package(), _problem(src), workspace=str(src))


def test_timeout_does_not_trigger_retries(tmp_path):
    """ADR 0007 A2: timeouts are boundary violations, not retryable model
    errors. The retry loop must not catch TimeoutExpired."""
    src = _src_workspace(tmp_path)
    pi = _make_mock_pi(tmp_path, stdout_lines=[], exit_code=0, sleep_seconds=1.0)
    sleeps: list[float] = []
    adapter = CliSubprocessAdapter(
        pi_binary=pi,
        retry_budget=5,
        backoff_seconds=(0.01,),
        sleep=sleeps.append,
        subprocess_timeout_seconds=0.05,
    )
    with pytest.raises(subprocess.TimeoutExpired):
        adapter.run(_package(), _problem(src), workspace=str(src))
    assert sleeps == [], "timeout must not engage the backoff/retry path"
