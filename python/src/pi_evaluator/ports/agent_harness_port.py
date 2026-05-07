"""AgentHarnessPort: boundary between the optimizer and (Pi + package)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.test_suite import GraduatedProblem
from ..domain.types import Package, RawTelemetry


@runtime_checkable
class AgentHarnessPort(Protocol):
    """Run (Pi + package) against a problem; return raw telemetry.

    Workspace materialization is an internal concern of the adapter.
    Scoring is a separate port; this one only produces raw telemetry.
    """

    def run(
        self,
        package: Package,
        problem: GraduatedProblem,
        workspace: str,
    ) -> RawTelemetry: ...
