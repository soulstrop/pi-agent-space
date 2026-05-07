"""Phase 1 stub adapter: returns canned RawTelemetry.

Phase 2 replaces this with a CliSubprocessAdapter that actually invokes
Pi as a subprocess against a materialized workspace.
"""

from __future__ import annotations

from ..domain.test_suite import GraduatedProblem
from ..domain.types import Package, RawTelemetry
from ..ports.agent_harness_port import AgentHarnessPort


class StubAgentHarnessAdapter(AgentHarnessPort):
    """Returns the canned ``RawTelemetry`` configured at construction."""

    def __init__(self, telemetry: RawTelemetry | None = None) -> None:
        self._telemetry = telemetry or RawTelemetry(events=[], exit_code=0)

    def run(
        self,
        package: Package,
        problem: GraduatedProblem,
        workspace: str,
    ) -> RawTelemetry:
        return self._telemetry
