"""Phase 3.5 acceptance test: real Pi, multi-trial optimizer driver.

Per ADR 0006 this is a *driver-mechanics* test, not a surrogate-quality
test — at 4 trials we sit below the bootstrap threshold (~10), so the
optimizer behaves like random search. We verify the loop machinery:
trials persist, the frontier writes, outcomes are well-typed, and the
run halts for a known reason.

Marker-gated and prerequisite-gated (ADR 0010):
  - ``@pytest.mark.acceptance_fast``: 1 trial, 0 retries, 1 problem.
    Run via ``uv run pytest -m acceptance_fast``.
  - ``@pytest.mark.acceptance_full``: 4 trials, default retries.
    Run via ``mise run test-acceptance-full``.
  Both delegate to ``_run()`` to prevent drift.

Skipped at runtime when ``pi`` is not on PATH or no recognised
provider API key is in the environment.

The test does NOT assert that any trial actually completed — model
non-determinism and expired keys can make every trial
``error_escalated``, and that is still a valid driver-mechanics
exercise per ADR 0007's outcome enumeration.
"""

from __future__ import annotations

import json
import os
import random
import shutil
from pathlib import Path

import pytest

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.random_from_slot_space import RandomFromSlotSpace
from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.types import EvalSuiteRef, VersionVector
from pi_evaluator.optimizer_driver import OptimizerDriver
from pi_evaluator.trial_runner import TrialRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"

_PROVIDER_FALLBACKS: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "google/gemini-2.5-flash"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
]

VALID_OUTCOMES = {"completed", "boundary_violation", "error_escalated"}


def _detect_model() -> str | None:
    for env_var, model in _PROVIDER_FALLBACKS:
        if os.environ.get(env_var):
            return model
    return None


def _suite_ref() -> EvalSuiteRef:
    return EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.74.0",
        package_versions={
            "read": "builtin",
            "write": "builtin",
            "edit": "builtin",
            "bash": "builtin",
        },
        eval_suite_version="0.1.0",
    )


def _slot_space_for(model: str) -> SlotSpace:
    """4-package Cartesian: 1 model × 2 skills × 2 prompts × 1 template."""
    return SlotSpace(
        models=[NamedValue(name=model.split("/")[-1], value=model)],
        skills_variants=[
            NamedValue(name="minimal", value=("read", "write")),
            NamedValue(name="expanded", value=("read", "write", "edit", "bash")),
        ],
        system_prompts=[
            NamedValue(
                name="terse",
                value="Solve the problem in the workspace. Stop when tests pass.",
            ),
            NamedValue(
                name="detailed",
                value=(
                    "You are a careful coding assistant. Inspect the workspace, "
                    "implement the requested function, and stop when the "
                    "validation tests would pass."
                ),
            ),
        ],
        template_value_variants=[NamedValue(name="default", value={})],
    )


def _run(
    tmp_path: Path,
    *,
    trial_budget: int,
    retry_budget: int,
) -> None:
    """Shared driver-mechanics exercise used by both acceptance variants.

    Asserts persistence shape, frontier file, and package dedup — the
    ADR 0006 driver-mechanics contract — regardless of budget size.
    """
    if shutil.which("pi") is None:
        pytest.skip("`pi` binary not on PATH")
    model = _detect_model()
    if model is None:
        pytest.skip(
            "no provider API key found "
            f"(looked for: {', '.join(v for v, _ in _PROVIDER_FALLBACKS)})"
        )

    trials_dir = tmp_path / "trials"
    persistence = PerTrialDirectoryAdapter(trials_dir)
    runner = TrialRunner(
        harness=CliSubprocessAdapter(pi_binary="pi", retry_budget=retry_budget),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(
            GRADUATED_PROBLEMS_DIR, problem_ids=["001_binary_search"]
        ),
    )
    proposer = RandomFromSlotSpace(
        slot_space=_slot_space_for(model),
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        rng=random.Random(42),
    )
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
    )

    result = driver.run(trial_budget=trial_budget)

    assert len(result.trials) == trial_budget
    assert result.halted_reason in {"budget", "exhausted"}

    for trial in result.trials:
        trial_dir = trials_dir / trial.trial_id
        assert (trial_dir / "config.json").exists()
        assert (trial_dir / "versions.json").exists()
        assert (trial_dir / "events.jsonl").exists()
        assert (trial_dir / "final.json").exists()
        final = json.loads((trial_dir / "final.json").read_text())
        assert final["outcome"] in VALID_OUTCOMES
        assert trial.outcome == final["outcome"]

    frontier_file = trials_dir / "frontier.json"
    assert frontier_file.exists()
    frontier = json.loads(frontier_file.read_text())
    proposed_ids = {t.trial_id for t in result.trials}
    assert set(frontier["trial_ids"]).issubset(proposed_ids)

    package_signatures = {
        (
            t.package.model,
            t.package.system_prompt,
            tuple(sorted(t.package.skills)),
            tuple(sorted(t.package.template_values.items())),
        )
        for t in result.trials
    }
    assert len(package_signatures) == len(result.trials)


@pytest.mark.acceptance_fast
def test_phase3_acceptance_fast(tmp_path):
    """ADR 0010 minimal-spend variant: 1 trial, 0 retries, 1 problem."""
    _run(tmp_path, trial_budget=1, retry_budget=0)


@pytest.mark.acceptance_full
def test_phase3_acceptance_end_to_end(tmp_path):
    """ADR 0010 full variant: 4 trials, default retry budget."""
    _run(tmp_path, trial_budget=4, retry_budget=2)
