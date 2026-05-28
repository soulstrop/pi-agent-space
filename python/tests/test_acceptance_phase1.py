"""Phase 1 acceptance test: end-to-end smoke of the trial pipeline.

Hand-coded baseline package + the v1 graduated_problems/ suite +
stub harness + stub scorer + real per-trial-directory persistence.
The full pipeline must produce a complete on-disk trial directory
whose events.jsonl shows configured → (eval, scored_objective)+ →
finalized.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.adapters.stub_scorer import StubScorer
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RawTelemetry,
    VersionVector,
)
from pi_evaluator.trial_runner import TrialRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"


def _baseline_package() -> Package:
    """The Phase-1 baseline: gemini-flash + a generic system prompt and
    a minimal tool/skill subset. Phase 2 supplies the real prompt and
    tool list when the CliSubprocessAdapter lands."""
    return Package(
        model="gemini-flash",
        system_prompt="You are a careful coding assistant.",
        skills=["read", "write", "edit", "bash"],
        template_values={},
    )


def test_phase1_acceptance_end_to_end(tmp_path):
    persistence = PerTrialDirectoryAdapter(tmp_path)
    suite_source = GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR)
    harness = StubAgentHarnessAdapter(
        telemetry=RawTelemetry(events=[{"kind": "tok", "n": 1234}], exit_code=0)
    )
    scorer = StubScorer(
        metrics=Metrics(
            tokens_consumed=1234,
            validation_pass_rate=1.0,
            quality_score=0.95,
        )
    )
    runner = TrialRunner(
        harness=harness,
        scorer=scorer,
        persistence=persistence,
        suite_source=suite_source,
        clock=lambda c=itertools.count(): f"2026-05-06T00:00:{next(c):02d}Z",
    )

    suite_ref = EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0")
    versions = VersionVector(
        pi_version="0.4.2",
        package_versions={"read": "1.0", "write": "1.0", "edit": "1.0", "bash": "1.0"},
        eval_suite_version="0.1.0",
    )

    trial = runner.run_trial(
        trial_id="t-acceptance-001",
        package=_baseline_package(),
        eval_suite_ref=suite_ref,
        version_vector=versions,
    )

    trial_dir = tmp_path / "t-acceptance-001"
    assert (trial_dir / "config.json").exists()
    assert (trial_dir / "versions.json").exists()
    assert (trial_dir / "events.jsonl").exists()
    assert (trial_dir / "final.json").exists()

    config = json.loads((trial_dir / "config.json").read_text())
    assert config["trial_id"] == "t-acceptance-001"
    assert config["package"]["model"] == "gemini-flash"
    assert config["package"]["skills"] == ["read", "write", "edit", "bash"]
    assert config["eval_suite_ref"] == {
        "suite_id": "coding_v1",
        "suite_version": "0.1.0",
    }

    on_disk_versions = json.loads((trial_dir / "versions.json").read_text())
    assert on_disk_versions["pi_version"] == "0.4.2"
    assert on_disk_versions["eval_suite_version"] == "0.1.0"

    event_lines = (trial_dir / "events.jsonl").read_text().splitlines()
    phases = [json.loads(ln)["phase"] for ln in event_lines]
    assert phases[0] == "configured"
    assert phases[-1] == "finalized"
    middle = phases[1:-1]
    # ADR 0012: each problem produces one `eval` then 4 `metric_record` events.
    per_problem = 5
    assert len(middle) % per_problem == 0
    assert all(
        middle[i * per_problem] == "eval" for i in range(len(middle) // per_problem)
    )
    assert all(
        middle[i * per_problem + j] == "metric_record"
        for i in range(len(middle) // per_problem)
        for j in range(1, per_problem)
    )

    n_problems = len(middle) // per_problem
    assert n_problems >= 1, "expected at least 001_binary_search to be loaded"

    final = json.loads((trial_dir / "final.json").read_text())
    assert final["metrics"]["tokens_consumed"] == 1234 * n_problems
    assert final["metrics"]["validation_pass_rate"] == 1.0
    assert final["metrics"]["quality_score"] == 0.95
    assert final["subjective_score"] is None

    # Returned in-memory Trial agrees with what landed on disk.
    assert trial.trial_id == "t-acceptance-001"
    assert trial.final_metrics is not None
    assert trial.final_metrics.tokens_consumed == 1234 * n_problems
    assert [e.phase for e in trial.events] == phases

    # Round-trip through the persistence adapter recovers the same trial.
    [reloaded] = persistence.load_trials()
    assert reloaded.trial_id == trial.trial_id
    assert reloaded.final_metrics == trial.final_metrics
    assert [e.phase for e in reloaded.events] == phases
