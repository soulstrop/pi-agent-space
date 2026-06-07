"""ObservabilityPort: operational metrics + phase tracing (S007, ADR 0022).

The seam through which the optimizer emits *operational* signal — how many
trials ran, what they cost, how long phases took — as distinct from:

* the **logging** layer (ADR 0015), which carries human-readable diagnostics; and
* ``PersistencePort`` (ADR 0003/0013), which durably stores per-trial
  *capability* artifacts.

v1 ships an in-process, stdlib-only adapter (``InProcessObservability``) that
aggregates into a ``run_summary.json`` and a structured log event. The port is
deliberately a thin sink (counter / value / span) so an OpenTelemetry adapter is
a later swap — deferred behind the same enterprise-deployment trigger as ADR
0015's OTel transport — rather than a v1 dependency.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from ..domain.types import RunSummary


@runtime_checkable
class ObservabilityPort(Protocol):
    """Emit operational counters, values, and phase-span timings for a run."""

    def increment(self, metric: str, value: int = 1) -> None:
        """Add to a named counter (e.g. ``"trials.completed"``)."""
        ...

    def record(self, metric: str, value: float) -> None:
        """Accumulate an observed value (e.g. ``"cost.dollars"``)."""
        ...

    def span(self, name: str) -> AbstractContextManager[None]:
        """Time the wrapped block under ``name``; record even on exception."""
        ...

    def finish_run(
        self, run_id: str, halted_reason: str, wallclock_seconds: float
    ) -> RunSummary:
        """Finalize the run: build (and durably emit) its ``RunSummary``.

        Called once per run by the driver, which supplies the authoritative
        ``wallclock_seconds`` from its own monotonic clock. Implementations may
        also persist the summary and/or emit a structured log event. Returns the
        in-memory summary regardless.
        """
        ...
