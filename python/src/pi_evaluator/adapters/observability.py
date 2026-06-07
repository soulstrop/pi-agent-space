"""In-process observability adapter (S007, ADR 0022).

Stdlib-only realization of ``ObservabilityPort``: accumulate counters, observed
values, and phase-span timings in memory, then on ``finish_run`` build a
``RunSummary``, persist it as ``run_summary.json`` in the run directory, and
emit a structured ``run_summary`` log event. ``NullObservability`` is the no-op
default so observability stays opt-in (mirroring ADR 0015's ``configure_logging``
posture) and unconfigured runs pay nothing.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path

from ..domain.run_paths import run_dir
from ..domain.types import RunSummary, SpanStats

logger = logging.getLogger(__name__)


class InProcessObservability:
    """Aggregate operational metrics in memory; emit them at run end.

    Counter names the optimizer driver uses map onto ``RunSummary`` fields:
    ``trials.total``/``trials.completed``/``trials.boundary_violation``/
    ``trials.error_escalated`` and the ``cost.dollars`` value series. Any other
    counters/values are accepted but not surfaced in the summary (forward room
    for new metrics without a schema change).

    When ``base_dir`` is set, ``finish_run`` writes ``run_summary.json`` into the
    run directory (ADR 0013 layout) via ``run_paths.run_dir`` — co-located with
    the persistence adapter's run files without depending on it.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_dir = Path(base_dir) if base_dir is not None else None
        self._monotonic = monotonic
        self._counters: dict[str, int] = {}
        self._values: dict[str, float] = {}
        self._spans: dict[str, list[float]] = {}

    def increment(self, metric: str, value: int = 1) -> None:
        self._counters[metric] = self._counters.get(metric, 0) + value

    def record(self, metric: str, value: float) -> None:
        self._values[metric] = self._values.get(metric, 0.0) + value

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = self._monotonic()
        try:
            yield
        finally:
            elapsed_ms = (self._monotonic() - start) * 1000.0
            self._spans.setdefault(name, []).append(elapsed_ms)

    def finish_run(
        self, run_id: str, halted_reason: str, wallclock_seconds: float
    ) -> RunSummary:
        summary = self._build_summary(run_id, halted_reason, wallclock_seconds)
        self._emit_log_event(summary)
        if self._base_dir is not None:
            self._write_artifact(summary)
        self._reset()
        return summary

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _build_summary(
        self, run_id: str, halted_reason: str, wallclock_seconds: float
    ) -> RunSummary:
        total = self._counters.get("trials.total", 0)
        per_minute = total / (wallclock_seconds / 60.0) if wallclock_seconds else 0.0
        spans = {
            name: SpanStats(
                count=len(samples),
                total_ms=sum(samples),
                mean_ms=sum(samples) / len(samples),
            )
            for name, samples in sorted(self._spans.items())
        }
        return RunSummary(
            run_id=run_id,
            halted_reason=halted_reason,
            trials_total=total,
            trials_completed=self._counters.get("trials.completed", 0),
            trials_boundary_violation=self._counters.get(
                "trials.boundary_violation", 0
            ),
            trials_error_escalated=self._counters.get("trials.error_escalated", 0),
            total_cost_dollars=self._values.get("cost.dollars", 0.0),
            wallclock_seconds=wallclock_seconds,
            trials_per_minute=per_minute,
            spans=spans,
        )

    def _emit_log_event(self, summary: RunSummary) -> None:
        # MD3-A correlation IDs (run_id/trial_id) are stamped by ContextFilter;
        # the flat fields here are the metric payload (snake_case, MD4-A).
        fields = asdict(summary)
        fields.pop("spans")  # nested; keep the log line flat and queryable
        logger.info("run summary", extra={"event": "run_summary", **fields})

    def _write_artifact(self, summary: RunSummary) -> None:
        assert self._base_dir is not None
        d = run_dir(self._base_dir, summary.run_id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / "run_summary.json"
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True))
        tmp.replace(path)

    def _reset(self) -> None:
        self._counters = {}
        self._values = {}
        self._spans = {}


class NullObservability:
    """No-op ``ObservabilityPort``: the default when observability is unconfigured.

    Counters, values, and spans are discarded; ``finish_run`` returns a zeroed
    ``RunSummary`` and never writes an artifact. Lets ``TrialRunner`` /
    ``OptimizerDriver`` call the seam unconditionally with zero overhead.
    """

    def increment(self, metric: str, value: int = 1) -> None:  # noqa: D102
        return None

    def record(self, metric: str, value: float) -> None:  # noqa: D102
        return None

    def span(self, name: str) -> AbstractContextManager[None]:  # noqa: D102
        return nullcontext()

    def finish_run(
        self, run_id: str, halted_reason: str, wallclock_seconds: float
    ) -> RunSummary:  # noqa: D102
        return RunSummary(
            run_id=run_id,
            halted_reason=halted_reason,
            trials_total=0,
            trials_completed=0,
            trials_boundary_violation=0,
            trials_error_escalated=0,
            total_cost_dollars=0.0,
            wallclock_seconds=wallclock_seconds,
            trials_per_minute=0.0,
            spans={},
        )
