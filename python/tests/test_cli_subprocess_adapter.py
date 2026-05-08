"""Tests for the real Pi CLI adapter, using a mock Pi script per test."""

from __future__ import annotations

import json
import stat
from pathlib import Path

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
) -> str:
    """Write a tiny Python script that mimics Pi for one test invocation.

    Optional ``log_invocation`` path receives a JSON dump of argv + cwd
    when the mock runs; tests inspect this to verify the adapter built
    the command correctly.
    """
    script = tmp_path / "mock_pi"
    parts = ["#!/usr/bin/env python3", "import json, os, sys"]
    if log_invocation is not None:
        parts.append(f"with open({str(log_invocation)!r}, 'w') as f:")
        parts.append("    json.dump({'argv': sys.argv, 'cwd': os.getcwd()}, f)")
    for line in stdout_lines or []:
        parts.append(f"print({line!r}, flush=True)")
    if stderr_text:
        parts.append(f"sys.stderr.write({stderr_text!r})")
    parts.append(f"sys.exit({exit_code})")
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
    adapter = CliSubprocessAdapter(pi_binary=pi)
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
    adapter = CliSubprocessAdapter(pi_binary=pi)
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
