from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import pytest

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.adapters.random_from_slot_space import RandomFromSlotSpace
from pi_evaluator.adapters.synthetic_suite_scorer import SyntheticSuiteScorer
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Package,
    RawTelemetry,
    ValidationResult,
    VersionVector,
)
from pi_evaluator.optimizer_driver import OptimizerDriver
from pi_evaluator.ports.agent_harness_port import AgentHarnessPort
from pi_evaluator.ports.eval_suite_source_port import EvalSuiteSourcePort
from pi_evaluator.trial_runner import TrialRunner


def _suite_ref() -> EvalSuiteRef:
    return EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.74.0", package_versions={}, eval_suite_version="0.1.0"
    )


def _slot_space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
        ],
        skills_variants=[
            NamedValue(name="minimal", value=("read", "write")),
        ],
        system_prompts=[NamedValue(name="v0", value="be concise")],
        template_value_variants=[NamedValue(name="default", value={})],
    )  # cartesian: 2


class _OneProblemSuite(EvalSuiteSourcePort):
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def load(self) -> list[GraduatedProblem]:
        return [
            GraduatedProblem(
                id="p1",
                title="P1",
                difficulty=1,
                prompt="solve",
                workspace_dir=str(self._workspace),
                validation_steps=[ValidationStep(name="v", command="true")],
                tags=[],
            )
        ]


class _PerModelHarness(AgentHarnessPort):
    """Returns synthetic Pi telemetry whose token/cost values depend on the
    package's model. Lets the driver tests exercise the full scoring pipeline
    (harness -> SyntheticSuiteScorer -> Metrics) with deterministic
    per-package behavior."""

    def __init__(self, metrics_by_model: dict[str, tuple[int, float, bool]]) -> None:
        self._metrics_by_model = metrics_by_model

    def run(
        self,
        package: Package,
        problem: GraduatedProblem,
        workspace: str,
    ) -> RawTelemetry:
        tokens, cost, passed = self._metrics_by_model[package.model]
        return RawTelemetry(
            events=[
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "usage": {
                            "totalTokens": tokens,
                            "cost": {"total": cost},
                        },
                    },
                }
            ],
            exit_code=0,
            validation_results=[
                ValidationResult(
                    step_name="v",
                    exit_code=0 if passed else 1,
                    stdout="",
                    stderr="",
                    passed=passed,
                )
            ],
        )


def _id_factory():
    counter = itertools.count(1)
    return lambda: f"trial-{next(counter):03d}"


def _driver(
    tmp_path: Path,
    *,
    metrics_by_model: dict[str, tuple[int, float, bool]] | None = None,
    seed: int = 0,
    trial_dir: Path | None = None,
    id_factory=None,
    per_trial_cost_cap_usd: float | None = None,
    per_run_cost_cap_usd: float | None = None,
    observability=None,
) -> tuple[OptimizerDriver, PerTrialDirectoryAdapter]:
    if metrics_by_model is None:
        metrics_by_model = {
            "google/gemini-2.5-flash": (100, 0.001, True),
            "anthropic/claude-haiku-4-5": (200, 0.005, True),
        }
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    persistence = PerTrialDirectoryAdapter(trial_dir or (tmp_path / "trials"))
    runner = TrialRunner(
        harness=_PerModelHarness(metrics_by_model),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=_OneProblemSuite(workspace),
        observability=observability,
    )
    proposer = RandomFromSlotSpace(
        slot_space=_slot_space(),
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        rng=random.Random(seed),
    )
    factory = id_factory if id_factory is not None else _id_factory()
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        trial_id_factory=factory,
        per_trial_cost_cap_usd=per_trial_cost_cap_usd,
        per_run_cost_cap_usd=per_run_cost_cap_usd,
        observability=observability,
    )
    return driver, persistence


def test_driver_runs_full_budget_of_trials(tmp_path):
    driver, persistence = _driver(tmp_path)
    result = driver.run(trial_budget=2)
    assert len(result.trials) == 2
    assert result.halted_reason == "budget"
    on_disk = persistence.load_trials()
    assert {t.trial_id for t in on_disk} == {"trial-001", "trial-002"}


def test_driver_halts_when_proposer_exhausted(tmp_path):
    """Slot space has 2 packages; budget of 5 should halt at 2."""
    driver, _ = _driver(tmp_path)
    result = driver.run(trial_budget=5)
    assert len(result.trials) == 2
    assert result.halted_reason == "exhausted"


def test_driver_writes_frontier_file_with_non_dominated_trial_ids(tmp_path):
    """flash dominates haiku on tokens and cost (both win), so the frontier
    contains only the flash trial."""
    driver, _ = _driver(tmp_path)
    driver.run(trial_budget=2)
    frontier_file = tmp_path / "trials" / "frontier.json"
    assert frontier_file.exists()
    data = json.loads(frontier_file.read_text())
    assert "trial_ids" in data
    assert len(data["trial_ids"]) == 1


def test_driver_keeps_both_trials_on_frontier_when_tradeoff_exists(tmp_path):
    """flash is token-cheap-but-quality-low; haiku is token-expensive-but-
    quality-high. Per ADR 0005, both stay on the frontier."""
    driver, _ = _driver(
        tmp_path,
        metrics_by_model={
            "google/gemini-2.5-flash": (50, 0.001, False),  # cheap, fails validation
            "anthropic/claude-haiku-4-5": (500, 0.005, True),  # expensive, passes
        },
    )
    driver.run(trial_budget=2)
    data = json.loads((tmp_path / "trials" / "frontier.json").read_text())
    assert len(data["trial_ids"]) == 2


def test_driver_frontier_updates_after_each_trial(tmp_path):
    """frontier.json reflects state after the most recent trial. With 1 trial
    in the budget, the frontier has exactly 1 member; after a second, it
    has 1 or 2 depending on dominance."""
    driver1, _ = _driver(tmp_path)
    driver1.run(trial_budget=1)
    after_one = json.loads((tmp_path / "trials" / "frontier.json").read_text())
    assert len(after_one["trial_ids"]) == 1


def test_driver_appends_to_existing_history(tmp_path):
    """A second driver run picks up where the first left off, deduping
    against the loaded history."""
    counter = itertools.count(1)
    shared_factory = lambda: f"trial-{next(counter):03d}"  # noqa: E731

    driver1, persistence = _driver(tmp_path, seed=1, id_factory=shared_factory)
    driver1.run(trial_budget=1)
    assert len(persistence.load_trials()) == 1

    driver2, _ = _driver(
        tmp_path,
        seed=2,
        trial_dir=tmp_path / "trials",
        id_factory=shared_factory,
    )
    result = driver2.run(trial_budget=5)
    # The proposer dedups against the trial from driver1; only one fresh
    # package remains, so the run halts as exhausted.
    assert result.halted_reason == "exhausted"
    assert len(result.trials) == 1
    assert len(persistence.load_trials()) == 2


def test_driver_passes_per_trial_cap_to_runner(tmp_path):
    """A per-trial cap configured on the driver produces boundary_violation
    trials when crossed."""
    driver, persistence = _driver(
        tmp_path,
        metrics_by_model={
            "google/gemini-2.5-flash": (100, 0.05, True),  # under cap
            "anthropic/claude-haiku-4-5": (200, 0.20, True),  # over cap
        },
        per_trial_cost_cap_usd=0.10,
    )
    driver.run(trial_budget=2)
    on_disk = persistence.load_trials()
    by_model = {t.package.model: t for t in on_disk}
    assert by_model["google/gemini-2.5-flash"].outcome == "completed"
    assert by_model["anthropic/claude-haiku-4-5"].outcome == "boundary_violation"


def test_per_run_cost_cap_halts_driver(tmp_path):
    """Each trial costs $0.06; cap=$0.10 → halts after second trial."""
    driver, _ = _driver(
        tmp_path,
        metrics_by_model={
            "google/gemini-2.5-flash": (100, 0.06, True),
            "anthropic/claude-haiku-4-5": (200, 0.06, True),
        },
        per_run_cost_cap_usd=0.10,
    )
    result = driver.run(trial_budget=5)
    assert result.halted_reason == "per_run_cost_cap"
    assert len(result.trials) == 2


def test_per_run_cost_cap_none_disables_check(tmp_path):
    """With cap=None, expensive trials don't halt the driver."""
    driver, _ = _driver(
        tmp_path,
        metrics_by_model={
            "google/gemini-2.5-flash": (100, 100.0, True),
            "anthropic/claude-haiku-4-5": (200, 100.0, True),
        },
        per_run_cost_cap_usd=None,
    )
    result = driver.run(trial_budget=5)
    assert result.halted_reason in ("budget", "exhausted")


def test_per_run_cost_cap_emits_warning_log(tmp_path, caplog):
    """Cumulative cost above warning fraction × cap → logged warning (once)."""
    import logging

    driver, _ = _driver(
        tmp_path,
        metrics_by_model={
            "google/gemini-2.5-flash": (100, 0.05, True),
            "anthropic/claude-haiku-4-5": (200, 0.05, True),
        },
        per_run_cost_cap_usd=0.10,
    )
    with caplog.at_level(logging.WARNING, logger="pi_evaluator.optimizer_driver"):
        driver.run(trial_budget=5)
    warnings = [
        r for r in caplog.records if "per-run cost cap" in r.getMessage().lower()
    ]
    assert len(warnings) == 1


class _SeqProposer:
    """Returns distinct packages one per call until exhausted.

    Distinct system_prompts ensure candidate-identity dedup doesn't
    re-cycle a previously-proposed package back through the loop.
    """

    def __init__(self, count: int) -> None:
        self._count = count
        self._called = 0

    def propose(self, history) -> Package | None:
        if self._called >= self._count:
            return None
        i = self._called
        self._called += 1
        return Package(
            model="google/gemini-2.5-flash",
            system_prompt=f"v{i}",
            skills=["read"],
            template_values={},
        )


class _OutcomeSeqHarness(AgentHarnessPort):
    """Returns telemetry whose outcome cycles through a configured sequence.

    Each entry maps to a per-call RawTelemetry:
      - ``"completed"`` → exit_code=0, no error
      - ``"error"``     → exit_code=1
      - ``"cost"``      → exit_code=0 but expensive (caller must set a
        per-trial cost cap below the configured cost to trigger
        boundary_violation)
    """

    def __init__(self, outcomes: list[str], cost_for_cost: float = 100.0) -> None:
        self._outcomes = outcomes
        self._cost = cost_for_cost
        self._called = 0

    def run(self, package, problem, workspace) -> RawTelemetry:
        outcome = self._outcomes[self._called]
        self._called += 1
        if outcome == "completed":
            return RawTelemetry(
                events=[
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "usage": {
                                "totalTokens": 1,
                                "cost": {"total": 0.0},
                            },
                        },
                    }
                ],
                exit_code=0,
                validation_results=[
                    ValidationResult(
                        step_name="v",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        passed=True,
                    )
                ],
            )
        if outcome == "error":
            return RawTelemetry(events=[], exit_code=1)
        if outcome == "cost":
            return RawTelemetry(
                events=[
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "usage": {
                                "totalTokens": 1,
                                "cost": {"total": self._cost},
                            },
                        },
                    }
                ],
                exit_code=0,
                validation_results=[
                    ValidationResult(
                        step_name="v",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        passed=True,
                    )
                ],
            )
        raise ValueError(f"unknown outcome {outcome}")


def _outcome_driver(
    tmp_path: Path,
    *,
    outcomes: list[str],
    proposer_count: int | None = None,
    cost_for_cost: float = 100.0,
    **driver_kwargs,
) -> tuple[OptimizerDriver, PerTrialDirectoryAdapter]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    persistence = PerTrialDirectoryAdapter(tmp_path / "trials")
    runner = TrialRunner(
        harness=_OutcomeSeqHarness(outcomes, cost_for_cost=cost_for_cost),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=_OneProblemSuite(workspace),
    )
    proposer = _SeqProposer(proposer_count or len(outcomes))
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        trial_id_factory=_id_factory(),
        **driver_kwargs,
    )
    return driver, persistence


def test_circuit_breaker_trips_on_consecutive_errors(tmp_path):
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "error", "error", "error", "error"],
        max_consecutive_errors=3,
    )
    result = driver.run(trial_budget=5)
    assert result.halted_reason == "circuit_breaker_errors"
    assert len(result.trials) == 3


def test_circuit_breaker_consecutive_errors_resets_on_completed(tmp_path):
    """[error, error, completed, error, error] never hits 3 in a row."""
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "error", "completed", "error", "error"],
        max_consecutive_errors=3,
    )
    result = driver.run(trial_budget=5)
    assert result.halted_reason in ("budget", "exhausted")
    assert len(result.trials) == 5


def test_circuit_breaker_consecutive_errors_none_disables(tmp_path):
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error"] * 4,
        max_consecutive_errors=None,
    )
    result = driver.run(trial_budget=4)
    assert result.halted_reason in ("budget", "exhausted")
    assert len(result.trials) == 4


def test_circuit_breaker_error_count_unaffected_by_boundary_violation(tmp_path):
    """boundary_violation does not reset the consecutive-errors counter.

    Sequence [error, cost, error] with per_trial_cap=$0.10 makes the
    middle trial a boundary_violation (cost=$1.00). The error counter
    stays at 1 across the boundary, then becomes 2 — at max=2 the third
    trial trips the breaker.
    """
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "cost", "error"],
        max_consecutive_errors=2,
        per_trial_cost_cap_usd=0.10,
        cost_for_cost=1.0,
    )
    result = driver.run(trial_budget=5)
    assert result.halted_reason == "circuit_breaker_errors"
    assert len(result.trials) == 3
    assert result.trials[1].outcome == "boundary_violation"


def test_circuit_breaker_trips_on_time_without_completed(tmp_path):
    """Fake clock advances 6s per call; max_time=10s → trips at trial 2."""
    from datetime import timedelta

    times = iter([0.0, 6.0, 12.0, 18.0, 24.0])
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "error", "error"],
        max_time_without_completed_trial=timedelta(seconds=10),
        monotonic_clock=lambda: next(times),
    )
    result = driver.run(trial_budget=3)
    assert result.halted_reason == "circuit_breaker_time"
    assert len(result.trials) == 2


def test_circuit_breaker_time_resets_on_completed_trial(tmp_path):
    """[error, completed, error] keeps the elapsed window short."""
    from datetime import timedelta

    times = iter([0.0, 6.0, 12.0, 18.0])
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "completed", "error"],
        max_time_without_completed_trial=timedelta(seconds=10),
        monotonic_clock=lambda: next(times),
    )
    result = driver.run(trial_budget=3)
    assert result.halted_reason in ("budget", "exhausted")
    assert len(result.trials) == 3


def test_circuit_breaker_time_none_disables(tmp_path):
    """max_time_without_completed_trial=None → no time-based trip."""
    times = iter([0.0, 1000.0, 2000.0, 3000.0])
    driver, _ = _outcome_driver(
        tmp_path,
        outcomes=["error", "error", "error"],
        max_time_without_completed_trial=None,
        monotonic_clock=lambda: next(times),
    )
    result = driver.run(trial_budget=3)
    assert result.halted_reason in ("budget", "exhausted")
    assert len(result.trials) == 3


def test_result_has_run_id(tmp_path):
    driver, _ = _driver(tmp_path)
    result = driver.run(trial_budget=1)
    assert isinstance(result.run_id, str) and len(result.run_id) > 0


def test_run_directory_created_with_expected_files(tmp_path):
    driver, persistence = _driver(tmp_path)
    result = driver.run(trial_budget=2)
    run_dir = tmp_path / "trials" / "runs" / result.run_id
    assert run_dir.is_dir()
    assert (run_dir / "run_config.json").exists()
    assert (run_dir / "run_events.jsonl").exists()
    assert (run_dir / "trial_manifest.jsonl").exists()


def test_run_events_bracket_the_run(tmp_path):
    import json

    driver, _ = _driver(tmp_path)
    result = driver.run(trial_budget=1)
    run_dir = tmp_path / "trials" / "runs" / result.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "run_events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    phases = [e["phase"] for e in events]
    assert phases[0] == "run_started"
    assert phases[-1] == "run_halted"
    assert events[-1]["payload"]["halted_reason"] == result.halted_reason


def test_trial_manifest_records_dispatched_and_closed(tmp_path):
    import json

    driver, _ = _driver(tmp_path, id_factory=_id_factory())
    result = driver.run(trial_budget=2)
    run_dir = tmp_path / "trials" / "runs" / result.run_id
    entries = [
        json.loads(line)
        for line in (run_dir / "trial_manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]
    statuses = [e["status"] for e in entries]
    assert statuses.count("dispatched") == 2
    assert statuses.count("closed") == 2


def test_trial_config_json_contains_run_id(tmp_path):
    import json

    driver, _ = _driver(tmp_path, id_factory=_id_factory())
    result = driver.run(trial_budget=1)
    trial_dirs = [
        d for d in (tmp_path / "trials").iterdir() if d.is_dir() and d.name != "runs"
    ]
    assert len(trial_dirs) == 1
    config = json.loads((trial_dirs[0] / "config.json").read_text())
    assert config["run_id"] == result.run_id


def test_replicates_greater_than_one_not_yet_supported(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    persistence = PerTrialDirectoryAdapter(tmp_path / "trials")
    runner = TrialRunner(
        harness=_PerModelHarness({"google/gemini-2.5-flash": (100, 0.001, True)}),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=_OneProblemSuite(workspace),
    )
    proposer = RandomFromSlotSpace(
        slot_space=_slot_space(),
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
    )
    with pytest.raises(NotImplementedError, match="replicates"):
        OptimizerDriver(
            runner=runner,
            proposer=proposer,
            persistence=persistence,
            eval_suite_ref=_suite_ref(),
            version_vector=_versions(),
            replicates=3,
        )


def _three_model_space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
            NamedValue(name="sonnet", value="anthropic/claude-sonnet-4-6"),
        ],
        skills_variants=[NamedValue(name="minimal", value=("read", "write"))],
        system_prompts=[NamedValue(name="v0", value="be concise")],
        template_value_variants=[NamedValue(name="default", value={})],
    )  # cartesian: 3


def test_driver_with_surrogate_proposer_completes_three_trial_run(tmp_path):
    """Acceptance criterion (pi-agent-space-pwf #1): OptimizerDriver wired
    with the real SurrogateProposer (HetGP + EHVI, RandomFromSlotSpace
    fallback) completes a 3-trial run without error. The first trials run
    below the bootstrap threshold (random fallback); once enough history
    accrues the surrogate fits and EHVI directs selection."""
    pytest.importorskip("botorch")
    from pi_evaluator.adapters.ehvi_acquisition import EHVIAcquisition
    from pi_evaluator.adapters.het_gp_surrogate import HetGPSurrogate
    from pi_evaluator.adapters.surrogate_proposer import SurrogateProposer
    from pi_evaluator.domain.featurize import FeatureEncoder

    space = _three_model_space()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    persistence = PerTrialDirectoryAdapter(tmp_path / "trials")
    runner = TrialRunner(
        harness=_PerModelHarness(
            {
                "google/gemini-2.5-flash": (100, 0.001, True),
                "anthropic/claude-haiku-4-5": (200, 0.005, True),
                "anthropic/claude-sonnet-4-6": (400, 0.02, True),
            }
        ),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=_OneProblemSuite(workspace),
    )
    surrogate = HetGPSurrogate(n_bootstrap=2)
    proposer = SurrogateProposer(
        surrogate=surrogate,
        acquisition=EHVIAcquisition(surrogate, n_mc_samples=32, seed=1),
        encoder=FeatureEncoder(space),
        slot_space=space,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        fallback=RandomFromSlotSpace(
            slot_space=space,
            eval_suite_ref=_suite_ref(),
            version_vector=_versions(),
            rng=random.Random(0),
        ),
    )
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        trial_id_factory=_id_factory(),
    )
    result = driver.run(trial_budget=3)
    assert len(result.trials) == 3
    assert result.halted_reason == "budget"  # budget consumed exactly
    assert all(t.outcome == "completed" for t in result.trials)
    # All three distinct packages were proposed (no repeats).
    assert len({t.package.model for t in result.trials}) == 3


def test_driver_emits_run_summary_with_observability(tmp_path: Path) -> None:
    """End-to-end: an injected InProcessObservability counts trial outcomes,
    times phases, and persists run_summary.json in the run directory (ADR 0022)."""
    from pi_evaluator.adapters.observability import InProcessObservability
    from pi_evaluator.domain.run_paths import run_dir

    trial_dir = tmp_path / "trials"
    obs = InProcessObservability(base_dir=trial_dir)
    driver, _ = _driver(tmp_path, trial_dir=trial_dir, observability=obs)

    result = driver.run(trial_budget=2)

    summary_path = run_dir(trial_dir, result.run_id) / "run_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["run_id"] == result.run_id
    assert summary["trials_total"] == 2
    assert summary["trials_completed"] == 2
    assert summary["total_cost_dollars"] > 0.0
    # Tracing pillar: both runner-level and driver-level spans aggregated.
    assert summary["spans"]["trial"]["count"] == 2
    assert summary["spans"]["harness.run"]["count"] == 2
    assert summary["spans"]["scorer.score_objective"]["count"] == 2


def test_driver_without_observability_writes_no_summary(tmp_path: Path) -> None:
    """Null default: the existing run path is unchanged when no obs is wired."""
    from pi_evaluator.domain.run_paths import run_dir

    trial_dir = tmp_path / "trials"
    driver, _ = _driver(tmp_path, trial_dir=trial_dir)
    result = driver.run(trial_budget=1)
    assert not (run_dir(trial_dir, result.run_id) / "run_summary.json").exists()
