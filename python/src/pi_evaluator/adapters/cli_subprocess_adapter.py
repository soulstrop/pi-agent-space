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
from ..ports.agent_harness_port import AgentHarnessPort
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
    ) -> None:
        self._pi = pi_binary
        self._retry_budget = retry_budget
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

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
            if not _is_retryable_error(telemetry):
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


def _is_retryable_error(telemetry: RawTelemetry) -> bool:
    """ADR 0007 retryable-error rule, mirroring TrialRunner._has_model_error.

    Kept local to the adapter (rather than imported from trial_runner)
    so the adapter doesn't depend on the orchestrator. The two
    predicates must stay in sync; both flow from ADR 0007 A2 source-
    of-kill classification.
    """
    if telemetry.exit_code != 0:
        return True
    for event in telemetry.events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        if message.get("stopReason") == "error":
            return True
    return False


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
