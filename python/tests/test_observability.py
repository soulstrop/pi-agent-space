"""Observability suite — operational metrics + phase tracing (S007, ADR 0022)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pi_evaluator.adapters.observability import (
    InProcessObservability,
    NullObservability,
)
from pi_evaluator.domain.run_paths import run_dir
from pi_evaluator.domain.types import RunSummary, SpanStats
from pi_evaluator.ports.observability_port import ObservabilityPort


class FakeClock:
    """Monotonic clock advanced by hand, in seconds."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TestProtocolConformance:
    def test_in_process_is_observability_port(self) -> None:
        assert isinstance(InProcessObservability(), ObservabilityPort)

    def test_null_is_observability_port(self) -> None:
        assert isinstance(NullObservability(), ObservabilityPort)


class TestRunPaths:
    def test_run_dir_matches_adr_0013_layout(self) -> None:
        assert run_dir(Path("/base"), "r1") == Path("/base/runs/r1")


class TestInProcessCounters:
    def test_finish_run_aggregates_counts_and_cost(self) -> None:
        obs = InProcessObservability()
        obs.increment("trials.total")
        obs.increment("trials.total")
        obs.increment("trials.completed")
        obs.increment("trials.boundary_violation")
        obs.record("cost.dollars", 1.5)
        obs.record("cost.dollars", 0.25)

        summary = obs.finish_run("r1", "budget", wallclock_seconds=60.0)

        assert isinstance(summary, RunSummary)
        assert summary.run_id == "r1"
        assert summary.halted_reason == "budget"
        assert summary.trials_total == 2
        assert summary.trials_completed == 1
        assert summary.trials_boundary_violation == 1
        assert summary.trials_error_escalated == 0
        assert summary.total_cost_dollars == pytest.approx(1.75)
        assert summary.wallclock_seconds == pytest.approx(60.0)
        assert summary.trials_per_minute == pytest.approx(2.0)

    def test_trials_per_minute_zero_when_no_wallclock(self) -> None:
        obs = InProcessObservability()
        obs.increment("trials.total")
        summary = obs.finish_run("r1", "budget", wallclock_seconds=0.0)
        assert summary.trials_per_minute == 0.0

    def test_finish_run_resets_state_for_next_run(self) -> None:
        obs = InProcessObservability()
        obs.increment("trials.total")
        obs.finish_run("r1", "budget", wallclock_seconds=1.0)
        second = obs.finish_run("r2", "exhausted", wallclock_seconds=1.0)
        assert second.trials_total == 0


class TestInProcessSpans:
    def test_span_records_timing_aggregates(self) -> None:
        clock = FakeClock()
        obs = InProcessObservability(monotonic=clock)

        with obs.span("harness.run"):
            clock.advance(0.010)
        with obs.span("harness.run"):
            clock.advance(0.030)

        summary = obs.finish_run("r1", "budget", wallclock_seconds=1.0)
        stats = summary.spans["harness.run"]
        assert isinstance(stats, SpanStats)
        assert stats.count == 2
        assert stats.total_ms == pytest.approx(40.0)
        assert stats.mean_ms == pytest.approx(20.0)

    def test_span_records_on_exception(self) -> None:
        clock = FakeClock()
        obs = InProcessObservability(monotonic=clock)
        with pytest.raises(ValueError):  # noqa: PT012
            with obs.span("harness.run"):
                clock.advance(0.005)
                raise ValueError("boom")
        summary = obs.finish_run("r1", "budget", wallclock_seconds=1.0)
        assert summary.spans["harness.run"].count == 1
        assert summary.spans["harness.run"].total_ms == pytest.approx(5.0)


class TestRunSummaryArtifact:
    def test_finish_run_writes_run_summary_json(self, tmp_path: Path) -> None:
        obs = InProcessObservability(base_dir=tmp_path)
        obs.increment("trials.total")
        obs.increment("trials.completed")
        obs.record("cost.dollars", 2.0)
        with obs.span("trial"):
            pass

        summary = obs.finish_run("r1", "budget", wallclock_seconds=30.0)

        path = run_dir(tmp_path, "r1") / "run_summary.json"
        assert path.exists()
        on_disk = json.loads(path.read_text())
        assert on_disk["run_id"] == "r1"
        assert on_disk["trials_completed"] == 1
        assert on_disk["total_cost_dollars"] == pytest.approx(2.0)
        assert on_disk["spans"]["trial"]["count"] == 1
        # Returned summary and persisted artifact agree.
        assert on_disk["halted_reason"] == summary.halted_reason

    def test_no_base_dir_means_no_file(self, tmp_path: Path) -> None:
        obs = InProcessObservability()  # no base_dir
        obs.increment("trials.total")
        obs.finish_run("r1", "budget", wallclock_seconds=1.0)
        assert not (run_dir(tmp_path, "r1") / "run_summary.json").exists()


class TestStructuredLogEvent:
    def test_finish_run_emits_run_summary_log_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        obs = InProcessObservability()
        obs.increment("trials.total")
        obs.increment("trials.completed")
        with caplog.at_level(logging.INFO, logger="pi_evaluator"):
            obs.finish_run("r1", "budget", wallclock_seconds=60.0)
        records = [
            r for r in caplog.records if getattr(r, "event", None) == "run_summary"
        ]
        assert len(records) == 1
        rec = records[0]
        assert getattr(rec, "run_id") == "r1"  # noqa: B009 (dynamic LogRecord field)
        assert getattr(rec, "trials_completed") == 1  # noqa: B009


class TestNullObservability:
    def test_methods_are_noops_and_summary_is_empty(self, tmp_path: Path) -> None:
        obs = NullObservability()
        obs.increment("trials.total", 5)
        obs.record("cost.dollars", 9.0)
        with obs.span("trial"):
            pass
        summary = obs.finish_run("r1", "budget", wallclock_seconds=10.0)
        assert summary.trials_total == 0
        assert summary.total_cost_dollars == 0.0
        assert summary.spans == {}
        # Null never writes an artifact, even were a base dir in play.
        assert not (run_dir(tmp_path, "r1") / "run_summary.json").exists()
