"""Real AgentHarnessPort: spawn the Pi binary and parse its JSON event stream.

Pi's ``--mode json`` produces line-delimited JSON events on stdout; the
adapter materializes the workspace (per ADR 0004), invokes Pi
non-interactively (``--print --no-session``) with the package's
configuration, and captures stdout + exit code into ``RawTelemetry``.

Per ADR 0007 B1, the adapter retries on transient error signals
(non-zero subprocess exit, or an assistant ``message_end`` with
``stopReason == "error"``) against the **same materialized workspace**.
Retry budget defaults to 2 (3 total attempts: 1 initial + 2 retries),
with exponential backoff at 30s / 60s. Persistent errors after the
budget exhausts return the last attempt's telemetry verbatim, leaving
``TrialRunner._classify_outcome`` to escalate the trial.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from ..domain.test_suite import GraduatedProblem, ValidationStep
from ..domain.types import Package, RawTelemetry, ValidationResult
from ..lifecycle import is_model_error
from ..ports.agent_harness_port import AgentHarnessPort
from ..ports.sandbox_port import SandboxPort
from .sandbox import NullSandbox
from .workspace import materialize_workspace

DEFAULT_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (30.0, 60.0)
"""Backoff schedule for ADR 0007 B1's adapter-layer retries.

Index ``i`` is the wait before retry ``i+1``. If the schedule is
shorter than the retry budget, the last entry is reused for further
retries."""


class CliSubprocessAdapter(AgentHarnessPort):
    """Spawn Pi as a subprocess; parse the JSON event stream off stdout."""

    def __init__(
        self,
        pi_binary: str = "pi",
        retry_budget: int = 2,
        backoff_seconds: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        sandbox: SandboxPort | None = None,
    ) -> None:
        self._pi = pi_binary
        self._retry_budget = retry_budget
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._sandbox: SandboxPort = sandbox if sandbox is not None else NullSandbox()

    def run(
        self,
        package: Package,
        problem: GraduatedProblem,
        workspace: str,
    ) -> RawTelemetry:
        materialized = materialize_workspace(workspace)
        last_telemetry: RawTelemetry | None = None
        for attempt in range(self._retry_budget + 1):
            if attempt > 0:
                idx = min(attempt - 1, len(self._backoff_seconds) - 1)
                self._sleep(self._backoff_seconds[idx])
            telemetry = self._run_once(package, problem, materialized)
            last_telemetry = telemetry
            if not is_model_error(telemetry):
                return telemetry
        assert last_telemetry is not None
        return last_telemetry

    def _run_once(
        self,
        package: Package,
        problem: GraduatedProblem,
        materialized: Path,
    ) -> RawTelemetry:
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
        sandboxed = self._sandbox.wrap(cmd, workspace=materialized)
        proc = subprocess.run(
            sandboxed.cmd,
            cwd=str(sandboxed.cwd),
            env=sandboxed.env,
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
