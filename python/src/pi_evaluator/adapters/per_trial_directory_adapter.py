"""Filesystem-backed persistence: per-trial and per-run directories (ADR 0003, ADR 0013)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ..domain.types import (
    EvalSuiteRef,
    Metrics,
    Outcome,
    Package,
    RunConfig,
    RunEvent,
    SubjectiveScore,
    Trial,
    TrialEvent,
    VersionVector,
)
from ..ports.persistence_port import PersistencePort


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PerTrialDirectoryAdapter(PersistencePort):
    """Filesystem-backed persistence.

    Trial layout (ADR 0003):
        <base>/<trial_id>/{config.json, versions.json, events.jsonl, final.json}

    Run layout (ADR 0013):
        <base>/runs/<run_id>/{run_config.json, run_events.jsonl, trial_manifest.jsonl}

    ``load_trials`` scans ``<base>/`` directly; the ``runs/`` subdirectory
    is skipped automatically because it contains no ``config.json`` /
    ``versions.json`` files.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Trial methods
    # ------------------------------------------------------------------

    def _trial_dir(self, trial_id: str) -> Path:
        return self._base / trial_id

    def save_trial(self, trial: Trial) -> None:
        d = self._trial_dir(trial.trial_id)
        d.mkdir(parents=True, exist_ok=True)
        config = {
            "trial_id": trial.trial_id,
            "run_id": trial.run_id,
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
        with (self._trial_dir(trial_id) / "events.jsonl").open("a") as f:
            f.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def finalize_trial(
        self,
        trial_id: str,
        final_metrics: Metrics,
        outcome: Outcome,
    ) -> None:
        d = self._trial_dir(trial_id)
        final = {
            "metrics": asdict(final_metrics),
            "outcome": outcome,
        }
        tmp = d / "final.json.tmp"
        tmp.write_text(json.dumps(final, indent=2, sort_keys=True))
        tmp.replace(d / "final.json")

    def save_frontier(self, trial_ids: list[str]) -> None:
        """Write ``frontier.json`` atomically (temp-then-rename, ADR 0003)."""
        payload = {"trial_ids": list(trial_ids)}
        tmp = self._base / "frontier.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self._base / "frontier.json")

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
            outcome: Outcome | None = None
            final_file = trial_dir / "final.json"
            if final_file.exists():
                final = json.loads(final_file.read_text())
                final_metrics = Metrics(**final["metrics"])
                outcome = final.get("outcome")
                if final.get("subjective_score"):
                    subjective = SubjectiveScore(**final["subjective_score"])
            trials.append(
                Trial(
                    trial_id=config["trial_id"],
                    run_id=config.get("run_id"),
                    package=package,
                    eval_suite_ref=eval_suite_ref,
                    version_vector=version_vector,
                    events=events,
                    final_metrics=final_metrics,
                    subjective_score=subjective,
                    outcome=outcome,
                )
            )
        return trials

    # ------------------------------------------------------------------
    # Run methods (ADR 0013)
    # ------------------------------------------------------------------

    def _run_dir(self, run_id: str) -> Path:
        return self._base / "runs" / run_id

    def create_run(self, run_id: str, config: RunConfig) -> None:
        d = self._run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        run_config_payload = {"run_id": run_id, **asdict(config)}
        (d / "run_config.json").write_text(
            json.dumps(run_config_payload, indent=2, sort_keys=True)
        )
        for fname in ("run_events.jsonl", "trial_manifest.jsonl"):
            f = d / fname
            if not f.exists():
                f.write_text("")

    def append_run_event(self, run_id: str, event: RunEvent) -> None:
        with (self._run_dir(run_id) / "run_events.jsonl").open("a") as f:
            f.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def record_trial_dispatched(self, run_id: str, trial_id: str) -> None:
        entry = {"status": "dispatched", "timestamp": _now(), "trial_id": trial_id}
        with (self._run_dir(run_id) / "trial_manifest.jsonl").open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def record_trial_closed(
        self, run_id: str, trial_id: str, outcome: Outcome
    ) -> None:
        entry = {
            "outcome": outcome,
            "status": "closed",
            "timestamp": _now(),
            "trial_id": trial_id,
        }
        with (self._run_dir(run_id) / "trial_manifest.jsonl").open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
