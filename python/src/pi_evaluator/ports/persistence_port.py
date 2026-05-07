"""PersistencePort: trial storage per ADR 0003 (per-trial directory layout)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.types import Metrics, SubjectiveScore, Trial, TrialEvent


@runtime_checkable
class PersistencePort(Protocol):
    """Operations over the four-file trial layout.

    Layout (per ADR 0003):
        trials/{trial_id}/{config.json, versions.json, events.jsonl, final.json}

    ``save_trial`` writes the static config + versions files for a new
    trial (no events yet). ``append_event`` adds one line to the trial's
    events.jsonl. ``finalize_trial`` writes final.json (closes the
    trial). ``load_trials`` rebuilds in-memory ``Trial`` values from
    disk; trials without final.json load as open (final_metrics=None).
    """

    def save_trial(self, trial: Trial) -> None: ...

    def append_event(self, trial_id: str, event: TrialEvent) -> None: ...

    def finalize_trial(
        self,
        trial_id: str,
        final_metrics: Metrics,
        subjective_score: SubjectiveScore | None = None,
    ) -> None: ...

    def load_trials(self) -> list[Trial]: ...
