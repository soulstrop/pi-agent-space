"""Per-trial directory adapter implementing PersistencePort per ADR 0003."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    SubjectiveScore,
    Trial,
    TrialEvent,
    VersionVector,
)
from ..ports.persistence_port import PersistencePort


class PerTrialDirectoryAdapter(PersistencePort):
    """Filesystem-backed persistence: one directory per trial."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _trial_dir(self, trial_id: str) -> Path:
        return self._base / trial_id

    def save_trial(self, trial: Trial) -> None:
        d = self._trial_dir(trial.trial_id)
        d.mkdir(parents=True, exist_ok=True)
        config = {
            "trial_id": trial.trial_id,
            "package": asdict(trial.package),
            "eval_suite_ref": asdict(trial.eval_suite_ref),
        }
        versions = asdict(trial.version_vector)
        (d / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True))
        (d / "versions.json").write_text(json.dumps(versions, indent=2, sort_keys=True))
        events_file = d / "events.jsonl"
        if not events_file.exists():
            events_file.write_text("")

    def append_event(self, trial_id: str, event: TrialEvent) -> None:
        d = self._trial_dir(trial_id)
        events_file = d / "events.jsonl"
        with events_file.open("a") as f:
            f.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def finalize_trial(
        self,
        trial_id: str,
        final_metrics: Metrics,
        subjective_score: SubjectiveScore | None = None,
    ) -> None:
        d = self._trial_dir(trial_id)
        final = {
            "metrics": asdict(final_metrics),
            "subjective_score": asdict(subjective_score) if subjective_score else None,
        }
        # Atomic write: temp + rename.
        tmp = d / "final.json.tmp"
        tmp.write_text(json.dumps(final, indent=2, sort_keys=True))
        tmp.replace(d / "final.json")

    def load_trials(self) -> list[Trial]:
        trials: list[Trial] = []
        if not self._base.exists():
            return trials
        for trial_dir in sorted(self._base.iterdir()):
            if not trial_dir.is_dir():
                continue
            config_file = trial_dir / "config.json"
            versions_file = trial_dir / "versions.json"
            if not (config_file.exists() and versions_file.exists()):
                continue
            config = json.loads(config_file.read_text())
            versions = json.loads(versions_file.read_text())
            package = Package(**config["package"])
            eval_suite_ref = EvalSuiteRef(**config["eval_suite_ref"])
            version_vector = VersionVector(**versions)
            events: list[TrialEvent] = []
            events_file = trial_dir / "events.jsonl"
            if events_file.exists():
                for line in events_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    events.append(TrialEvent(**json.loads(line)))
            final_metrics: Metrics | None = None
            subjective: SubjectiveScore | None = None
            final_file = trial_dir / "final.json"
            if final_file.exists():
                final = json.loads(final_file.read_text())
                final_metrics = Metrics(**final["metrics"])
                if final.get("subjective_score"):
                    subjective = SubjectiveScore(**final["subjective_score"])
            trials.append(
                Trial(
                    trial_id=config["trial_id"],
                    package=package,
                    eval_suite_ref=eval_suite_ref,
                    version_vector=version_vector,
                    events=events,
                    final_metrics=final_metrics,
                    subjective_score=subjective,
                )
            )
        return trials
