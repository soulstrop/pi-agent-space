"""Filesystem-backed persistence: per-trial and per-run directories.

ADR 0003, ADR 0013.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ..domain.redaction import redact_json
from ..domain.run_paths import run_dir
from ..domain.tolerant_read import tolerant
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

logger = logging.getLogger(__name__)

# On-disk schema version stamped on every trial/run directory (ADR 0019 D1).
# Mirrors the release SemVer ``MAJOR.MINOR``; patch is omitted because a patch
# release never changes the persisted schema (D2). Bump on any minor release
# that changes the persisted layout. The drift guard in test_persistence keeps
# this in lockstep with pyproject's project version.
SCHEMA_VERSION = "0.1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_major_minor(version: str) -> tuple[int, int]:
    """Parse ``"MAJOR.MINOR"`` (patch tolerated) into an ``(int, int)`` pair."""
    major, minor = (int(part) for part in version.split(".")[:2])
    return major, minor


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
    # I/O primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _append_jsonl(path: Path, obj: dict) -> None:
        """Append one canonical-JSON line to a .jsonl file.

        Telemetry is redacted of known provider-key shapes before it touches
        disk (ADR 0020 D1): ``events.jsonl`` carries raw stderr and malformed
        stdout lines that may contain secrets the agent printed.
        """
        with path.open("a") as f:
            f.write(json.dumps(redact_json(obj), sort_keys=True) + "\n")

    @staticmethod
    def _check_schema_version(file_version: object, *, where: str) -> None:
        """Compare an on-disk schema stamp against the reader (ADR 0019).

        Never raises — the read proceeds in every case; this only emits the
        appropriate log. Field-level tolerance (dropping unknown keys) is the
        separate tolerant-reader seam (pi-agent-space-963).

        - Missing/unparseable stamp: pre-stamp or malformed file; proceed
          silently (D7 / legacy).
        - Same major, file minor > reader minor: proceed, log info — the file
          may carry additive fields this reader will ignore (D4).
        - Same major, file minor <= reader minor: proceed silently (D3).
        - Different major: cross-major compatibility is deferred (D6); proceed
          best-effort and log a warning.
        """
        if not isinstance(file_version, str):
            return
        try:
            file_major, file_minor = _parse_major_minor(file_version)
        except (ValueError, IndexError):
            logger.warning(
                "unparseable schema_version; reading best-effort",
                extra={
                    "event": "schema_version_unparseable",
                    "where": where,
                    "file_schema_version": file_version,
                },
            )
            return
        reader_major, reader_minor = _parse_major_minor(SCHEMA_VERSION)
        if file_major != reader_major:
            logger.warning(
                "schema major mismatch; reading best-effort (cross-major deferred)",
                extra={
                    "event": "schema_version_major_mismatch",
                    "where": where,
                    "file_schema_version": file_version,
                    "reader_schema_version": SCHEMA_VERSION,
                },
            )
            return
        if file_minor > reader_minor:
            logger.info(
                "file written by newer minor schema; unknown fields are ignored",
                extra={
                    "event": "schema_version_newer_minor",
                    "where": where,
                    "file_schema_version": file_version,
                    "reader_schema_version": SCHEMA_VERSION,
                },
            )

    @staticmethod
    def _write_atomic(path: Path, payload: dict) -> None:
        """Write pretty-printed JSON via temp-then-rename (ADR 0003)."""
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Trial methods
    # ------------------------------------------------------------------

    def _trial_dir(self, trial_id: str) -> Path:
        return self._base / trial_id

    def save_trial(self, trial: Trial) -> None:
        d = self._trial_dir(trial.trial_id)
        d.mkdir(parents=True, exist_ok=True)
        config = {
            "schema_version": SCHEMA_VERSION,
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
        self._append_jsonl(self._trial_dir(trial_id) / "events.jsonl", asdict(event))

    def finalize_trial(
        self,
        trial_id: str,
        final_metrics: Metrics,
        outcome: Outcome,
    ) -> None:
        self._write_atomic(
            self._trial_dir(trial_id) / "final.json",
            {"metrics": asdict(final_metrics), "outcome": outcome},
        )

    def write_subjective_score(self, trial_id: str, ss: SubjectiveScore) -> None:
        d = self._trial_dir(trial_id)
        final = json.loads((d / "final.json").read_text())
        if final.get("outcome") != "completed":
            raise ValueError(
                f"write_subjective_score requires outcome=completed; "
                f"trial {trial_id!r} has outcome={final.get('outcome')!r}"
            )
        self._write_atomic(d / "subjective.json", asdict(ss))

    def save_frontier(self, trial_ids: list[str]) -> None:
        """Write ``frontier.json`` atomically (temp-then-rename, ADR 0003)."""
        self._write_atomic(self._base / "frontier.json", {"trial_ids": list(trial_ids)})

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
            self._check_schema_version(
                config.get("schema_version"), where=trial_dir.name
            )
            package = tolerant(
                Package, config["package"], where="config.json:package"
            )
            eval_suite_ref = tolerant(
                EvalSuiteRef,
                config["eval_suite_ref"],
                where="config.json:eval_suite_ref",
            )
            version_vector = tolerant(VersionVector, versions, where="versions.json")
            events: list[TrialEvent] = []
            events_file = trial_dir / "events.jsonl"
            if events_file.exists():
                for line in events_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    events.append(
                        tolerant(TrialEvent, json.loads(line), where="events.jsonl")
                    )
            final_metrics: Metrics | None = None
            subjective: SubjectiveScore | None = None
            outcome: Outcome | None = None
            final_file = trial_dir / "final.json"
            if final_file.exists():
                final = json.loads(final_file.read_text())
                final_metrics = tolerant(
                    Metrics, final["metrics"], where="final.json:metrics"
                )
                outcome = final.get("outcome")
            subjective_file = trial_dir / "subjective.json"
            if subjective_file.exists():
                subjective = tolerant(
                    SubjectiveScore,
                    json.loads(subjective_file.read_text()),
                    where="subjective.json",
                )
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
        return run_dir(self._base, run_id)

    def create_run(self, run_id: str, config: RunConfig) -> None:
        d = self._run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        run_config_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            **asdict(config),
        }
        (d / "run_config.json").write_text(
            json.dumps(run_config_payload, indent=2, sort_keys=True)
        )
        for fname in ("run_events.jsonl", "trial_manifest.jsonl"):
            f = d / fname
            if not f.exists():
                f.write_text("")

    def append_run_event(self, run_id: str, event: RunEvent) -> None:
        self._append_jsonl(self._run_dir(run_id) / "run_events.jsonl", asdict(event))

    def record_trial_dispatched(self, run_id: str, trial_id: str) -> None:
        self._append_jsonl(
            self._run_dir(run_id) / "trial_manifest.jsonl",
            {"status": "dispatched", "timestamp": _now(), "trial_id": trial_id},
        )

    def record_trial_closed(
        self, run_id: str, trial_id: str, outcome: Outcome
    ) -> None:
        self._append_jsonl(
            self._run_dir(run_id) / "trial_manifest.jsonl",
            {
                "outcome": outcome,
                "status": "closed",
                "timestamp": _now(),
                "trial_id": trial_id,
            },
        )
