"""Phase 6.5 acceptance test: real Pi, surrogate-directed proposal.

Where Phase 3's acceptance test sits *below* the bootstrap threshold (so
the optimizer behaves like random search), this test seeds a biased,
token-heavy history *above* the threshold so the ``SurrogateProposer``
actually fits the GP and lets EHVI direct the next proposal.

Shape:
  1. Seed a token-heavy history with stub trials over distinct in-space
     packages (cheap; no Pi).  With ``n_bootstrap`` seeds the surrogate
     fits, so the proposer is surrogate-directed rather than random.
  2. Run the ``OptimizerDriver`` wired with the real ``SurrogateProposer``
     (HetGP + EHVI, RandomFromSlotSpace fallback) for ``trial_budget``
     real-Pi trials.
  3. Assert the surrogate fit, each real proposal carries a candidate
     identity distinct from every seeded package (the proposer found
     something new), the outcomes are well-typed, and the Pareto frontier
     is non-empty.

Marker-gated and prerequisite-gated (ADR 0010):
  - ``@pytest.mark.acceptance_fast``: 1 real trial, 0 retries.
  - ``@pytest.mark.acceptance_full``: 2 real trials, default retries.
  Both delegate to ``_run()`` to prevent drift.

Skipped at runtime when ``pi`` is not on PATH or no recognised provider
API key is in the environment.  Like Phase 3, it does NOT require any
real trial to *complete* — model non-determinism can yield
``error_escalated``, and the seeded frontier keeps the frontier-non-empty
assertion honest regardless.
"""

from __future__ import annotations

import json
import os
import random
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter
from pi_evaluator.adapters.ehvi_acquisition import EHVIAcquisition
from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.adapters.het_gp_surrogate import HetGPSurrogate
from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.random_from_slot_space import RandomFromSlotSpace
from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.adapters.surrogate_proposer import SurrogateProposer
from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.featurize import FeatureEncoder
from pi_evaluator.domain.identity import candidate_identity
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RawTelemetry,
    SubjectiveScore,
    Trial,
    VersionVector,
)
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

# Low enough that a handful of cheap stub seeds crosses it.
_N_BOOTSTRAP = 3
_N_SEED = 4


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
        package_versions={"read": "builtin", "write": "builtin", "edit": "builtin"},
        eval_suite_version="0.1.0",
    )


def _slot_space_for(model: str) -> SlotSpace:
    """6-package Cartesian: 1 model × 2 skills × 3 prompts × 1 template."""
    return SlotSpace(
        models=[NamedValue(name=model.split("/")[-1], value=model)],
        skills_variants=[
            NamedValue(name="minimal", value=("read", "write")),
            NamedValue(name="expanded", value=("read", "write", "edit")),
        ],
        system_prompts=[
            NamedValue(name="terse", value="Solve it. Stop when tests pass."),
            NamedValue(name="plain", value="Implement the requested function."),
            NamedValue(
                name="detailed",
                value=(
                    "You are a careful coding assistant. Inspect the workspace, "
                    "implement the function, and stop when validation passes."
                ),
            ),
        ],
        template_value_variants=[NamedValue(name="default", value={})],
    )


class _FixedScorer:
    """Returns constant token-heavy metrics — used only for stub seeding."""

    def __init__(self, tokens: int, dollars: float, quality: float) -> None:
        self._m = Metrics(
            tokens_consumed=tokens,
            cost_dollars=dollars,
            validation_pass_rate=quality,
            quality_score=quality,
        )

    def score_objective(self, telemetry: RawTelemetry) -> Metrics:
        return self._m

    def score_subjective(self, trial: Trial) -> SubjectiveScore | None:
        return None


def _identity(package: Package) -> str:
    return candidate_identity(
        asdict(package), asdict(_suite_ref()), asdict(_versions())
    )


def _seed_history(trials_dir: Path, packages: list[Package]) -> None:
    """Persist token-heavy stub trials (one problem each) so the surrogate
    has a biased, above-bootstrap training set before real Pi runs.

    Tokens/cost/quality vary slightly per package so the GP heads see
    spread rather than a single constant.
    """
    for i, pkg in enumerate(packages):
        runner = TrialRunner(
            harness=StubAgentHarnessAdapter(),
            scorer=_FixedScorer(
                tokens=5000 + i * 800,
                dollars=0.40 + i * 0.05,
                quality=0.55 + i * 0.03,
            ),
            persistence=PerTrialDirectoryAdapter(trials_dir),
            suite_source=GraduatedProblemSetAdapter(
                GRADUATED_PROBLEMS_DIR, problem_ids=["001_binary_search"]
            ),
        )
        runner.run_trial(f"seed-{i:02d}", pkg, _suite_ref(), _versions())


def _run(tmp_path: Path, *, trial_budget: int, retry_budget: int) -> None:
    if shutil.which("pi") is None:
        pytest.skip("`pi` binary not on PATH")
    model = _detect_model()
    if model is None:
        pytest.skip(
            "no provider API key found "
            f"(looked for: {', '.join(v for v, _ in _PROVIDER_FALLBACKS)})"
        )

    slot_space = _slot_space_for(model)
    all_packages = list(slot_space.iter_packages())
    seed_packages = all_packages[:_N_SEED]
    assert len(all_packages) - _N_SEED >= trial_budget, (
        "slot space must leave at least trial_budget unseen packages"
    )

    trials_dir = tmp_path / "trials"
    _seed_history(trials_dir, seed_packages)

    persistence = PerTrialDirectoryAdapter(trials_dir)
    runner = TrialRunner(
        harness=CliSubprocessAdapter(pi_binary="pi", retry_budget=retry_budget),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(
            GRADUATED_PROBLEMS_DIR, problem_ids=["001_binary_search"]
        ),
    )
    surrogate = HetGPSurrogate(n_bootstrap=_N_BOOTSTRAP)
    proposer = SurrogateProposer(
        surrogate=surrogate,
        acquisition=EHVIAcquisition(surrogate, n_mc_samples=64, seed=0),
        encoder=FeatureEncoder(slot_space),
        slot_space=slot_space,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        fallback=RandomFromSlotSpace(
            slot_space=slot_space,
            eval_suite_ref=_suite_ref(),
            version_vector=_versions(),
            rng=random.Random(42),
        ),
    )
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
    )

    result = driver.run(trial_budget=trial_budget)

    # The seeded history (≥ n_bootstrap) means the surrogate fit and the
    # proposer was surrogate-directed, not a random fallback.
    assert surrogate.is_fitted

    assert len(result.trials) == trial_budget
    assert result.halted_reason in {"budget", "exhausted"}

    # Each real proposal is a package never seen in the seeded history.
    seed_identities = {_identity(p) for p in seed_packages}
    for trial in result.trials:
        assert _identity(trial.package) not in seed_identities
        assert trial.outcome in VALID_OUTCOMES
        trial_dir = trials_dir / trial.trial_id
        assert (trial_dir / "final.json").exists()
        final = json.loads((trial_dir / "final.json").read_text())
        assert final["outcome"] == trial.outcome

    # Proposals are mutually distinct (history dedup across the run).
    real_identities = {_identity(t.package) for t in result.trials}
    assert len(real_identities) == len(result.trials)

    # Final Pareto frontier contains at least one entry (seeds guarantee it).
    frontier_file = trials_dir / "frontier.json"
    assert frontier_file.exists()
    frontier = json.loads(frontier_file.read_text())
    assert len(frontier["trial_ids"]) >= 1


@pytest.mark.acceptance_fast
def test_phase6_acceptance_fast(tmp_path):
    """ADR 0010 minimal-spend variant: 1 surrogate-directed trial, 0 retries."""
    _run(tmp_path, trial_budget=1, retry_budget=0)


@pytest.mark.acceptance_full
def test_phase6_acceptance_end_to_end(tmp_path):
    """ADR 0010 full variant: 2 surrogate-directed trials, default retries."""
    _run(tmp_path, trial_budget=2, retry_budget=2)
