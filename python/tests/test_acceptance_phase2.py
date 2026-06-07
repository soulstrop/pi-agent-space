"""Phase 2 acceptance test: real Pi against 001_binary_search.

Marker-gated and prerequisite-gated (ADR 0010):
  - ``@pytest.mark.acceptance_fast``: 0 retries. Minimal spend.
    Run via ``uv run pytest -m acceptance_fast``.
  - ``@pytest.mark.acceptance_full``: default retry budget.
    Run via ``mise run test-acceptance-full``.
  Both delegate to ``_run()`` to prevent drift.
  - Skipped at runtime when ``pi`` is not on PATH or no recognised
    provider API key is in the environment.

The test exercises the full Phase 2 pipeline:
  - GraduatedProblemSetAdapter loads ``001_binary_search`` (pinned via
    ``problem_ids=["001_binary_search"]`` so the test does not silently
    expand once 002+ problems land under Phase 4.1).
  - CliSubprocessAdapter spawns the real ``pi`` binary in a
    materialized workspace.
  - Validation runs after Pi exits.
  - SyntheticSuiteScorer derives Metrics from the resulting telemetry.
  - PerTrialDirectoryAdapter persists the trial.

We assert pipeline mechanics (files written, events flow, final
metrics computed). We do NOT assert that the agent actually solved
the problem — that is a separate quality question and would make
the test flaky against model nondeterminism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acceptance_support import GRADUATED_PROBLEMS_DIR, require_pi_and_model
from builders import make_eval_suite_ref, make_version_vector

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.sandbox import select_sandbox
from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.types import Package
from pi_evaluator.trial_runner import TrialRunner


def _run(tmp_path: Path, *, retry_budget: int) -> None:
    """Shared pipeline-mechanics exercise used by both acceptance variants."""
    model = require_pi_and_model()

    package = Package(
        model=model,
        system_prompt=(
            "You are a careful coding assistant. Solve the problem in the "
            "given workspace using the available tools. Stop when the "
            "validation tests would pass."
        ),
        skills=["read", "write", "edit", "bash"],
        template_values={},
    )

    persistence = PerTrialDirectoryAdapter(tmp_path)
    runner = TrialRunner(
        harness=CliSubprocessAdapter(
            pi_binary="pi",
            retry_budget=retry_budget,
            sandbox=select_sandbox(pi_binary="pi"),
        ),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(
            GRADUATED_PROBLEMS_DIR, problem_ids=["001_binary_search"]
        ),
    )

    trial = runner.run_trial(
        trial_id="phase2-acceptance",
        package=package,
        eval_suite_ref=make_eval_suite_ref(suite_id="coding_v1", suite_version="0.1.0"),
        version_vector=make_version_vector(
            pi_version="0.73.0",
            package_versions={
                "read": "builtin",
                "write": "builtin",
                "edit": "builtin",
                "bash": "builtin",
            },
            eval_suite_version="0.1.0",
        ),
    )

    # All four trial files materialized.
    trial_dir = tmp_path / "phase2-acceptance"
    assert (trial_dir / "config.json").exists()
    assert (trial_dir / "versions.json").exists()
    assert (trial_dir / "events.jsonl").exists()
    assert (trial_dir / "final.json").exists()

    # The trial closed (objective scoring + finalize ran).
    assert trial.final_metrics is not None

    # Phase sequence per ADR 0012: configured → (eval, metric_record×4)+ → finalized.
    phases = [e.phase for e in trial.events]
    assert phases[0] == "configured"
    assert phases[-1] == "finalized"
    middle = phases[1:-1]
    assert middle, "expected at least one (eval, metric_record×4) group"
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

    # Real Pi produced events on stdout (session header at minimum).
    final = json.loads((trial_dir / "final.json").read_text())
    assert "metrics" in final
    assert isinstance(final["metrics"]["tokens_consumed"], int)
    assert isinstance(final["metrics"]["validation_pass_rate"], float)
    # ADR 0007 outcome classification: must be set, must be a known value.
    assert final["outcome"] in {"completed", "boundary_violation", "error_escalated"}
    assert trial.outcome == final["outcome"]


@pytest.mark.acceptance_fast
def test_phase2_acceptance_fast(tmp_path):
    """ADR 0010 minimal-spend variant: single trial, 0 retries."""
    _run(tmp_path, retry_budget=0)


@pytest.mark.acceptance_full
def test_phase2_acceptance_end_to_end(tmp_path):
    """ADR 0010 full variant: single trial, default retry budget."""
    _run(tmp_path, retry_budget=2)
