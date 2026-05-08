"""Real AgentHarnessPort: spawn the Pi binary and parse its JSON event stream.

Pi's ``--mode json`` produces line-delimited JSON events on stdout; the
adapter materializes the workspace (per ADR placeholder), invokes Pi
non-interactively (``--print --no-session``) with the package's
configuration, and captures stdout + exit code into ``RawTelemetry``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..domain.test_suite import GraduatedProblem, ValidationStep
from ..domain.types import Package, RawTelemetry, ValidationResult
from ..ports.agent_harness_port import AgentHarnessPort
from .workspace import materialize_workspace


class CliSubprocessAdapter(AgentHarnessPort):
    """Spawn Pi as a subprocess; parse the JSON event stream off stdout."""

    def __init__(self, pi_binary: str = "pi") -> None:
        self._pi = pi_binary

    def run(
        self,
        package: Package,
        problem: GraduatedProblem,
        workspace: str,
    ) -> RawTelemetry:
        materialized = materialize_workspace(workspace)
        cmd = [
            self._pi,
            "--print",
            "--no-session",
            "--mode",
            "json",
        ]
        if package.model:
            cmd.extend(["--model", package.model])
        if package.system_prompt:
            cmd.extend(["--system-prompt", package.system_prompt])
        if package.skills:
            cmd.extend(["--tools", ",".join(package.skills)])
        cmd.append(problem.prompt)
        proc = subprocess.run(
            cmd,
            cwd=str(materialized),
            capture_output=True,
            text=True,
            check=False,
        )
        validation_results = [
            _run_validation_step(step, materialized)
            for step in problem.validation_steps
        ]
        events, malformed_lines = _parse_event_stream(proc.stdout)
        return RawTelemetry(
            events=events,
            exit_code=proc.returncode,
            validation_results=validation_results,
            stderr=proc.stderr,
            malformed_lines=malformed_lines,
        )


def _run_validation_step(step: ValidationStep, workspace: Path) -> ValidationResult:
    proc = subprocess.run(
        step.command,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        shell=True,
        check=False,
    )
    return ValidationResult(
        step_name=step.name,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        passed=proc.returncode == step.expected_exit_code,
    )


def _parse_event_stream(stdout: str) -> tuple[list[dict], list[str]]:
    """Split Pi's stdout into parsed events and preserved malformed lines.

    Pi's ``--mode json`` is line-delimited JSON, but warnings or
    non-JSON noise can intermix. Lines that fail to parse are kept
    verbatim so lifecycle classification can flag a malformed run.
    """
    events: list[dict] = []
    malformed: list[str] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            malformed.append(line)
    return events, malformed
