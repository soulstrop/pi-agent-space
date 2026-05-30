"""PersistencePort: trial and run storage per ADR 0003 and ADR 0013."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.types import (
    Metrics,
    Outcome,
    RunConfig,
    RunEvent,
    Trial,
    TrialEvent,
)


@runtime_checkable
class PersistencePort(Protocol):
    """Operations over the trial and run directory layouts.

    Trial layout (ADR 0003):
        <base>/{trial_id}/{config.json, versions.json, events.jsonl, final.json}

    Run layout (ADR 0013):
        <base>/runs/{run_id}/{run_config.json, run_events.jsonl, trial_manifest.jsonl}

    Trial methods: ``save_trial``, ``append_event``, ``finalize_trial``,
    ``load_trials``, ``save_frontier``.

    Run methods: ``create_run``, ``append_run_event``,
    ``record_trial_dispatched``, ``record_trial_closed``.
    """

    def save_trial(self, trial: Trial) -> None: ...

    def append_event(self, trial_id: str, event: TrialEvent) -> None: ...

    def finalize_trial(
        self,
        trial_id: str,
        final_metrics: Metrics,
        outcome: Outcome,
    ) -> None: ...

    def load_trials(self) -> list[Trial]: ...

    def save_frontier(self, trial_ids: list[str]) -> None: ...

    def create_run(self, run_id: str, config: RunConfig) -> None: ...

    def append_run_event(self, run_id: str, event: RunEvent) -> None: ...

    def record_trial_dispatched(self, run_id: str, trial_id: str) -> None: ...

    def record_trial_closed(
        self, run_id: str, trial_id: str, outcome: Outcome
    ) -> None: ...
