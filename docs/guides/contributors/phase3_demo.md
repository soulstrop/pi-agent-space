# Phase 3 Acceptance Test — Multi-Trial Optimizer Driver

*2026-05-28T03:23:22Z by Showboat 0.6.1*
<!-- showboat-id: 17058c88-c0dc-4326-94ff-5f45e0723486 -->

## Overview

`tests/test_acceptance_phase3.py` (called "Phase 3.5" internally) layers the **optimizer driver** on top of the Phase 2 pipeline. Phase 2 ran a single trial against a hand-built `Package`; Phase 3 runs a *budgeted multi-trial loop* where a proposer samples packages from a `SlotSpace` and the driver persists a frontier across trials.

Per **ADR 0006**, this is a *driver-mechanics* test, not a surrogate-quality test. At 4 trials we sit well below the bootstrap threshold (~10), so the optimizer behaves like random search — that is the point. We verify the **loop machinery**: trials persist, the frontier writes, outcomes are well-typed, halt reason is known, packages are unique.

All commands below run from the `python/` directory.

## Feature 1 — `OptimizerDriver` orchestrates a budgeted multi-trial loop

The driver is the Phase-3 addition. It wraps a `TrialRunner` (Phase 2's pipeline) with a `proposer` that produces packages and a `trial_budget` that caps the loop. `driver.run(...)` returns a result with `trials` and a `halted_reason` that must be one of `{"budget", "exhausted"}` — i.e. the loop stopped for a known, enumerated reason, not by accident.

```python
    driver = OptimizerDriver(
        runner=runner,
        proposer=proposer,
        persistence=persistence,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
    )

    result = driver.run(trial_budget=4)

    # Driver mechanics: every proposed trial materialized on disk.
    assert len(result.trials) == 4
    assert result.halted_reason in {"budget", "exhausted"}

```

## Feature 2 — `SlotSpace`: the package configuration Cartesian product

A `SlotSpace` declares the discrete dimensions a proposer can sample over. Each dimension is a list of `NamedValue`s — the name is for telemetry/dedup, the value is what actually lands in the `Package`. Phase 3 uses a deliberately tiny 4-cell space (1 model × 2 skill-variants × 2 prompts × 1 template), which exactly matches the `trial_budget=4` so the proposer must enumerate the whole space.

```python
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
```

## Feature 3 — `RandomFromSlotSpace` with a seeded RNG, and history-aware dedup

The proposer samples from the slot space using `random.Random(42)` — seeded so the test is reproducible — and dedups against the trials already accepted by the driver. The test pins this down by checking that no two trials share the same package signature (model, prompt, sorted skills, sorted template-values). Combined with `trial_budget == |SlotSpace|`, this forces the proposer to *enumerate* the space without repeats.

```python
    proposer = RandomFromSlotSpace(
        slot_space=_slot_space_for(model),
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        rng=random.Random(42),
    )

    # The proposer dedups against history — no two trials share a Package.
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
```

## Feature 4 — `frontier.json`: the new cross-trial artifact

Where Phase 2 wrote only per-trial directories, the optimizer driver also writes a *trials-directory-level* `frontier.json` listing the Pareto-frontier trial IDs. The test asserts both that it exists and that every ID it references was actually proposed (i.e. no stale or fabricated entries).

```python
    # Frontier file is present and references only proposed trial IDs.
    frontier_file = trials_dir / "frontier.json"
    assert frontier_file.exists()
    frontier = json.loads(frontier_file.read_text())
    proposed_ids = {t.trial_id for t in result.trials}
    assert set(frontier["trial_ids"]).issubset(proposed_ids)
```

## Feature 5 — Problem-ID filter on the suite source

To keep multi-trial cost bounded, the suite source is constructed with an explicit `problem_ids=["001_binary_search"]` filter. The `GraduatedProblemSetAdapter` honors this filter — only the named problem(s) load, even if `graduated_problems/` later grows to hundreds of entries. (This filter was hardened in Phase 3.5.1 — see `bd show` history around `feat(3.5.1): add problem_ids filter`.)

```python
    runner = TrialRunner(
        harness=CliSubprocessAdapter(pi_binary="pi"),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(
            GRADUATED_PROBLEMS_DIR, problem_ids=["001_binary_search"]
        ),
    )
```

## Feature 6 — Driver mechanics, not surrogate quality (ADR 0006 + 0007)

Two deliberate non-assertions, both anchored in ADRs:

- **ADR 0006 (bootstrap threshold).** Below ~10 trials the optimizer cannot learn — it behaves like random search. At `trial_budget=4` we are explicitly in the sub-bootstrap regime, so the test cannot and does not check that later trials are "better" than earlier ones. It only checks that the loop ran cleanly.
- **ADR 0007 (outcome enumeration).** Every trial's `outcome` must be one of `{completed, boundary_violation, error_escalated}`, but the test does *not* require any of the four to be `completed`. Model nondeterminism or an expired API key can produce all-`error_escalated` runs, and that is still a valid exercise of the driver loop.

This is the same scope discipline as Phase 2: pin down the contract that's actually under test, leave quality questions to the metric distributions consumed by the optimizer.

## Proof — the test runs (or skips cleanly)

Same gating as Phase 2: `@pytest.mark.acceptance` plus runtime skips for missing `pi` or missing provider keys. In this environment `pi` is installed but no API keys are exported, so the test skips with the exact gating message:

```bash
uv run pytest tests/test_acceptance_phase3.py -m acceptance -v -rs 2>&1 | tail -10 | sed -E 's/in [0-9.]+s/in N.NNs/'
```

```output
cachedir: .pytest_cache
rootdir: /home/mikeco/projects/pi-agent-space/python
configfile: pyproject.toml
collecting ... collected 1 item

tests/test_acceptance_phase3.py::test_phase3_acceptance_end_to_end SKIPPED [100%]

=========================== short test summary info ============================
SKIPPED [1] tests/test_acceptance_phase3.py:111: no provider API key found (looked for: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY)
============================== 1 skipped in N.NNs ==============================
```

## What changed from Phase 2

| Concern                  | Phase 2                                  | Phase 3                                          |
|--------------------------|------------------------------------------|--------------------------------------------------|
| Loop                     | Single `runner.run_trial(...)`            | `OptimizerDriver.run(trial_budget=N)`            |
| Package source           | Hand-built fixture                       | Sampled from `SlotSpace` by `RandomFromSlotSpace` |
| RNG                      | n/a                                      | Seeded (`random.Random(42)`) for reproducibility |
| Halt condition           | n/a                                      | `halted_reason ∈ {budget, exhausted}`            |
| Suite scope              | Whole suite                              | `problem_ids=["001_binary_search"]` filter       |
| Per-trial artifacts      | 4 files per trial                        | unchanged (4 files per trial)                    |
| Cross-trial artifacts    | none                                     | `frontier.json` at trials-dir root                |
| Quality assertion        | Pipeline mechanics only                  | Driver mechanics only (sub-bootstrap, ADR 0006)  |
| Outcome tolerance        | `outcome` is one of three values         | All four trials may be `error_escalated` (ADR 0007) |
| Harness / scorer / runner / event stream | — | unchanged                                        |

Phase 4 graduates above the bootstrap threshold and lets the optimizer's surrogate actually matter — but Phase 3 has to lock down the loop machinery first.
