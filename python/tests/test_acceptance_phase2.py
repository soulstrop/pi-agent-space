"""Phase 2 acceptance test: real Pi against 001_binary_search.

Marker-gated and prerequisite-gated:
  - ``@pytest.mark.acceptance_full`` (ADR 0010) so the default ``mise
    run test`` skips it. Run via ``mise run test-acceptance-full``.
    The matching ``acceptance_fast`` variant is filed as follow-up
    work — see beads issues opened against ADR 0010.
  - Skipped at runtime when ``pi`` is not on PATH or no recognised
    provider API key is in the environment.

The test exercises the full Phase 2 pipeline:
  - GraduatedProblemSetAdapter loads ``001_binary_search``.
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
import os
import shutil
from pathlib import Path

import pytest

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.types import EvalSuiteRef, Package, VersionVector
from pi_evaluator.trial_runner import TrialRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"

# Order is preference — first available key wins. Each entry maps an
# API-key env var to a Pi "provider/model" string.
_PROVIDER_FALLBACKS: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "google/gemini-2.5-flash"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
]


def _detect_model() -> str | None:
    for env_var, model in _PROVIDER_FALLBACKS:
        if os.environ.get(env_var):
            return model
    return None


@pytest.mark.acceptance_full
def test_phase2_acceptance_end_to_end(tmp_path):
    if shutil.which("pi") is None:
        pytest.skip("`pi` binary not on PATH")
    model = _detect_model()
    if model is None:
        pytest.skip(
            "no provider API key found "
            f"(looked for: {', '.join(v for v, _ in _PROVIDER_FALLBACKS)})"
        )

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
        harness=CliSubprocessAdapter(pi_binary="pi"),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR),
    )

    trial = runner.run_trial(
        trial_id="phase2-acceptance",
        package=package,
        eval_suite_ref=EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0"),
        version_vector=VersionVector(
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

    # Phase sequence is configured → (eval, scored_objective)+ → finalized.
    phases = [e.phase for e in trial.events]
    assert phases[0] == "configured"
    assert phases[-1] == "finalized"
    middle = phases[1:-1]
    assert middle, "expected at least one (eval, scored_objective) pair"
    assert all(middle[i] == "eval" for i in range(0, len(middle), 2))
    assert all(middle[i] == "scored_objective" for i in range(1, len(middle), 2))

    # Real Pi produced events on stdout (session header at minimum).
    final = json.loads((trial_dir / "final.json").read_text())
    assert "metrics" in final
    assert isinstance(final["metrics"]["tokens_consumed"], int)
    assert isinstance(final["metrics"]["validation_pass_rate"], float)
    # ADR 0007 outcome classification: must be set, must be a known value.
    assert final["outcome"] in {"completed", "boundary_violation", "error_escalated"}
    assert trial.outcome == final["outcome"]
