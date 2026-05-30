"""Phase 5.2: pi-eval score CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    Trial,
    VersionVector,
)


def _setup_completed_trial(base: Path, trial_id: str = "t-001") -> None:
    adapter = PerTrialDirectoryAdapter(base)
    t = Trial(
        trial_id=trial_id,
        package=Package(model="gemini-flash", system_prompt="", skills=[], template_values={}),
        eval_suite_ref=EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0"),
        version_vector=VersionVector(pi_version="0.4.2", package_versions={}, eval_suite_version="1.0.0"),
    )
    adapter.save_trial(t)
    adapter.finalize_trial(trial_id, Metrics(tokens_consumed=10, validation_pass_rate=1.0, quality_score=0.9), "completed")


def _run_score_cmd(base: Path, trial_id: str, score: str, scorer: str, notes: str = "") -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable, "-m", "pi_evaluator.cli.score",
        "--base-dir", str(base),
        "--trial-id", trial_id,
        "--score", score,
        "--scorer", scorer,
    ]
    if notes:
        cmd += ["--notes", notes]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(base.parent))


class TestScoreCLIHappyPath:
    def test_creates_subjective_json(self, tmp_path):
        _setup_completed_trial(tmp_path)
        result = _run_score_cmd(tmp_path, "t-001", "0.85", "user:alice", "looks good")
        assert result.returncode == 0, result.stderr
        sidecar = json.loads((tmp_path / "t-001" / "subjective.json").read_text())
        assert sidecar["score"] == pytest.approx(0.85)
        assert sidecar["scorer"] == "user:alice"
        assert sidecar["notes"] == "looks good"
        assert "timestamp" in sidecar

    def test_notes_defaults_to_empty_string(self, tmp_path):
        _setup_completed_trial(tmp_path)
        result = _run_score_cmd(tmp_path, "t-001", "0.5", "user:alice")
        assert result.returncode == 0, result.stderr
        sidecar = json.loads((tmp_path / "t-001" / "subjective.json").read_text())
        assert sidecar["notes"] == ""

    def test_score_round_trips_through_load_trials(self, tmp_path):
        _setup_completed_trial(tmp_path)
        _run_score_cmd(tmp_path, "t-001", "0.7", "user:bob", "decent")
        adapter = PerTrialDirectoryAdapter(tmp_path)
        [loaded] = adapter.load_trials()
        assert loaded.subjective_score is not None
        assert loaded.subjective_score.score == pytest.approx(0.7)
        assert loaded.subjective_score.scorer == "user:bob"


class TestScoreCLIErrorCases:
    def test_exits_nonzero_for_non_completed_trial(self, tmp_path):
        adapter = PerTrialDirectoryAdapter(tmp_path)
        t = Trial(
            trial_id="t-bad",
            package=Package(model="gemini-flash", system_prompt="", skills=[], template_values={}),
            eval_suite_ref=EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0"),
            version_vector=VersionVector(pi_version="0.4.2", package_versions={}, eval_suite_version="1.0.0"),
        )
        adapter.save_trial(t)
        adapter.finalize_trial("t-bad", Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0), "boundary_violation")
        result = _run_score_cmd(tmp_path, "t-bad", "0.5", "user:alice")
        assert result.returncode != 0

    def test_exits_nonzero_for_score_out_of_range(self, tmp_path):
        _setup_completed_trial(tmp_path)
        result = _run_score_cmd(tmp_path, "t-001", "1.5", "user:alice")
        assert result.returncode != 0

    def test_exits_nonzero_for_negative_score(self, tmp_path):
        _setup_completed_trial(tmp_path)
        result = _run_score_cmd(tmp_path, "t-001", "-0.1", "user:alice")
        assert result.returncode != 0
