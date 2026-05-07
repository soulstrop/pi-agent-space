# Implementation Plan

This document defines a phased, TDD-driven implementation plan for the Python production code in `python/`. Each phase delivers an end-to-end vertical slice of functionality so that interface-level feedback arrives early. Within each phase, steps are sequenced by dependency and parallelized where the graph allows.

## Principles

- **Vertical slices.** Each phase produces a working pipeline end-to-end at its current fidelity, not a stack of disconnected modules.
- **TDD red-green-refactor.** Every step starts with a failing test, advances to the minimum code that turns it green, and ends with refactor while staying green.
- **Independence.** Steps are written so the dependency graph is explicit and parallel work is possible where allowed.
- **Interface review at every phase boundary.** Surface interface-level issues (port shapes, schema gaps, abstraction warts) before starting the next phase, since later phases would compound any drift.
- **Python per ADR 0001; Haskell as thinking tool.** Implementation lives in `python/`; reconciliation against `haskell/` and `math.pdf` is post hoc, not lockstep.
- **v1 targets the R&D synthetic deployment scenario.** Individual and enterprise A/B journeys remain reachable as future adapters behind the same ports.

## TDD cadence

For each step:
1. **Red.** Write a failing test that names the smallest behavioral expectation for the unit under construction. The test must fail for the right reason — the symptom should be the missing capability, not a syntax error or import issue.
2. **Green.** Write the minimum production code that makes the test pass. Resist generalizing beyond what the test demands.
3. **Refactor.** With tests green, restructure for clarity (extracting helpers, renaming, deduplicating) without changing observable behavior. Run all existing tests to confirm.

Prefer many small commits over one large one; each commit should leave the suite green.

## Layer model

The production code is organized as ports and adapters per ADR 0002. Five ports:

| Port | Responsibility | v1 R&D adapter |
| --- | --- | --- |
| `AgentHarnessPort` | Run (Pi + package) against a materialized workspace; return raw telemetry. | `CliSubprocessAdapter` |
| `ScoringPort` | Map raw telemetry → objective metrics; ingest subjective scores. | `SyntheticSuiteScorer` |
| `PersistencePort` | Persist trials per ADR 0003 (per-trial directory, append-only events). | `PerTrialDirectoryAdapter` |
| `EvalSuiteSourcePort` | Load a graduated problem set from `graduated_problems/`. | `GraduatedProblemSetAdapter` |
| `PackageProposerPort` | Propose the next package given trial history. | `RandomFromSlotSpace` → `SurrogateProposer` (Phase 6) |

The orchestrator is `TrialRunner`, which composes these ports to execute one trial.

**Note on existing scaffolding.** `python/src/pi_evaluator/` originally contained a stub `AgentHarnessPort` that returned `Metrics` directly, conflating execution and scoring. Phase 1 Step 1.5 refactored this so `AgentHarnessPort.run` returns raw telemetry and `ScoringPort` derives metrics — preserving the existing module structure but cleaning the interface.

**Phase 1 outcomes feeding later phases.**

- `TrialRunner` lives at `pi_evaluator/trial_runner.py` (no `application/` layer yet) and threads `problem.workspace_dir` to `AgentHarnessPort.run` verbatim. Phase 2.1's tmpdir copy lives inside the adapter — the runner's contract is unchanged.
- Aggregation across problems (`sum(tokens)`, `mean(rates)`, `mean(quality)`) lives in a private `_aggregate` helper inside `TrialRunner`. Phase 4's capability profile either lifts this to a `MetricAggregatorPort` or replaces it inline; the existence of this helper is the starting point.
- `PersistencePort.finalize_trial(trial_id, final_metrics, subjective_score=None)` is one-shot at trial close. Phase 5's async-subjective path needs an additional method (or explicit re-finalize semantics) so that subjective scores can land after the trial closes without re-running objective scoring.
- Float precision bites trivially-symmetric aggregates (e.g., `mean([0.8, 0.8, 0.8]) == 0.8000000000000002`). Tests across Phases 4–6 must use `pytest.approx` for any aggregated rate/quality metric.

---

## Phase 1 — Single-trial smoke pipeline

**Goal.** End-to-end trial pipeline runs with stub `AgentHarnessPort` and real persistence, producing a valid trial directory on disk per ADR 0003. Validates the trial schema, file layout, event-stream model, and port boundaries.

**Deliverable.** Running the pipeline produces a real trial directory at `trials/{id}/{config.json, versions.json, events.jsonl, final.json}`. No real Pi execution yet.

**Steps.**

- **1.1 Domain types.** *Independent of all other steps.* Define `Package`, `Trial`, `TrialEvent`, `Metrics`, `EvalSuiteRef`, `VersionVector` as dataclasses with explicit fields and types. The existing `GraduatedProblem` (`python/src/pi_evaluator/domain/test_suite.py`) stays. One TDD cycle per type. Add pytest as a dev dependency in `pyproject.toml` if not already there.

- **1.2 Candidate-change identity.** *Independent.* Implement a canonical hash over `(package_diff_from_baseline, eval_suite_ref, version_vector)` per the trial-event-stream design. TDD: identical inputs hash equal; semantically equivalent JSON variants hash equal (test canonicalization including key order and whitespace).

- **1.3 PersistencePort + PerTrialDirectoryAdapter.** *Depends on 1.1.* Implement `save_trial`, `append_event`, `finalize_trial`, `load_trials`. The four-file layout is the contract. TDD: round-trip a hand-built trial; event-append idempotency; partial-state recovery (a trial without `final.json` loads as an open trial).

- **1.4 ScoringPort + stub.** *Independent of 1.3, depends on 1.1.* Define `score_objective(raw_telemetry) -> ObjectiveMetrics` and `score_subjective(...) -> Optional[SubjectiveScore]` on the port; provide a stub adapter returning fixed values. TDD: stub returns the configured metrics regardless of input.

- **1.5 AgentHarnessPort refactor + stub.** *Independent of 1.3/1.4, depends on 1.1.* Refactor the existing port: `run(package, problem, workspace) -> RawTelemetry` (currently returns `Metrics`). Keep a stub adapter for Phase 1. TDD: stub returns canned telemetry; verify the port no longer mentions `Metrics`.

- **1.6 EvalSuiteSourcePort + GraduatedProblemSetAdapter.** *Independent of 1.3/1.4/1.5, depends on 1.1.* Load problems from `graduated_problems/`. TDD: loading `001_binary_search` yields a `GraduatedProblem` with the expected fields.

- **1.7 TrialRunner.** *Depends on 1.1, 1.3, 1.4, 1.5, 1.6.* Orchestrates configuration event → for each problem, run agent + score → finalize → persist. TDD: a pipeline run produces a complete on-disk trial directory and returns the in-memory `Trial`.

- **1.8 Acceptance test.** *Depends on 1.7.* End-to-end: hand-coded baseline package, single-problem suite, stub harness; assert the trial directory has all expected files with valid contents and `events.jsonl` shows the configured → eval → scored → final phase sequence.

Steps 1.1 and 1.2 can begin in parallel. After 1.1, steps 1.3, 1.4, 1.5, 1.6 are all parallel-able. 1.7 and 1.8 are sequential at the tail.

**Interface-review checkpoint.** Before Phase 2:
- Are the four files (`config.json`, `versions.json`, `events.jsonl`, `final.json`) the right cut, or do some collapse / split?
- Is `RawTelemetry` the right shape, or does the harness need to return more / less?
- Where does workspace materialization live — inside `AgentHarnessPort.run` or as a separate concern?
- Does `ScoringPort` cleanly separate objective from subjective, or are they entangled?
- Is the candidate-identity hash canonical enough for downstream dedup?

---

## Phase 2 — Real Pi execution

**Goal.** Replace the stub `AgentHarnessPort` with a `CliSubprocessAdapter` that actually invokes Pi against a materialized workspace and returns real telemetry; replace the stub `ScoringPort` with one that derives objective metrics from that telemetry.

**Deliverable.** Running the pipeline against `001_binary_search` causes Pi to actually attempt the problem, the validation tests run, and the resulting trial captures real token usage and real pass/fail.

**Steps.**

- **2.1 Workspace materialization helper.** *Independent.* Copy `GraduatedProblem.workspace_dir` into a temp directory the trial can mutate; return the temp path. v1 isolation strategy: tmpdir copy. (Workspace isolation gets a future ADR; this is the placeholder.) **Per Phase 1's contract,** materialization is invoked by the harness adapter, not by `TrialRunner` — the runner continues to pass `problem.workspace_dir` through unchanged.

- **2.2 CliSubprocessAdapter.** *Depends on 2.1.* Spawn Pi as a subprocess against the materialized workspace, with the package's prompt/system-prompt/template-values surfaced via Pi's CLI flags or a generated `pi.json`. The adapter calls the workspace helper from 2.1 internally before spawning Pi. Capture Pi's stdout event stream and exit code into `RawTelemetry`. TDD: a fixture mocking Pi (a tiny script standing in) verifies the adapter parses the event stream and returns the expected `RawTelemetry`.

- **2.3 Validation execution.** *Depends on 2.2.* After Pi finishes, run each `ValidationStep.command` in the materialized workspace; capture exit codes. **Extends `RawTelemetry`** with a `validation_results: list[ValidationResult]` field carrying `(step_name, exit_code, stdout, stderr)` per step, so scoring stays a pure function of telemetry. TDD: validation against a workspace where the agent succeeded and one where it failed.

- **2.4 Real `SyntheticSuiteScorer`.** *Depends on 2.2, 2.3.* Derive `tokens_consumed` from Pi telemetry, `validation_pass_rate` from `RawTelemetry.validation_results` exit codes, `quality_score` as a simple synthetic (e.g., validation pass rate × 1.0 — intentionally minimal in v1; weights and additional axes land in their own ADR). Per-trial cross-problem aggregation continues to live in `TrialRunner._aggregate`; the scorer is per-(telemetry → metrics) only. TDD: known telemetry → expected metrics.

- **2.5 Acceptance test.** *Depends on 2.4 + Phase 1.7.* End-to-end with real Pi, the v0 baseline package (gemini-flash + supplied system prompt + Read/Write/Edit/Bash tool subset), single graduated problem; assert the trial directory contains real metrics from a real run. Requires Pi installed; document under a contributors-guide note.

**Interface-review checkpoint.** Before Phase 3:
- Is `RawTelemetry` a stable shape across Pi versions, or does drift in Pi's CLI/event-stream surface require versioning?
- Does the adapter cleanly handle Pi failures (timeout, crash, malformed events)?
- Is workspace materialization durable enough as a placeholder, or does Phase 3's multi-trial cadence force the isolation ADR sooner?
- Did the package configuration shape survive contact with Pi's actual CLI surface?

---

## Phase 3 — Multi-config search, random proposer, basic Pareto

**Goal.** Run multiple package configurations against the suite, persist all trials, and compute a Pareto frontier from history. No surrogate model yet — random proposer over a declared slot space.

**Deliverable.** Running the optimizer produces N trial directories and a Pareto frontier output identifying the non-dominated configurations.

**Steps.**

- **3.1 Slot/value space schema.** *Independent.* Declare slots and candidate values (the v0 baseline + at least one alternative per slot per the seed-variations decision). TDD: enumerating the space yields the expected Cartesian product (or sampled subset).

- **3.2 RandomFromSlotSpace proposer.** *Depends on 3.1.* `propose(history) -> Package` as uniform random over the declared space, excluding configurations already evaluated (by candidate-identity from 1.2). TDD: with mocked history, proposer skips already-evaluated identities; without history, samples freely.

- **3.3 Pareto frontier (2D).** *Independent.* Compute the Pareto frontier over `(mean_cost, mean_quality)` from a list of trials. TDD: hand-verified frontier members on a known trial set.

- **3.4 Optimizer driver.** *Depends on 3.2, 3.3, Phase 2.* Loop: load history → propose → run trial → persist → recompute frontier. Bounded by a trial budget. TDD: with a stub harness that returns deterministic metrics by config, the driver produces the expected frontier within budget.

- **3.5 Acceptance test.** *Depends on 3.4.* Run the optimizer against the real Pi for a small budget (~4–6 trials) over the slot space; assert all trials persist and a frontier file is generated.

Steps 3.1 and 3.3 can begin in parallel.

**Interface-review checkpoint.** Before Phase 4:
- Does the slot/value schema generalize cleanly to template values (per the templated-prompts memory)? Or does it need a sub-schema for templated content?
- Is the proposer's history-aware dedup working, and is the candidate-identity hash robust under slot rearrangement?
- Should `PackageProposerPort` be split into `Proposer` + `BudgetPolicy`?

---

## Phase 4 — Capability profile and scaling slope

**Goal.** Per-(problem, metric) records flow through the pipeline; trial-level metrics are derived as capability profiles; Pareto axes include the scaling slope.

**Deliverable.** Trials over a multi-difficulty suite produce capability profiles whose scaling slope distinguishes "uniformly moderate" from "cheap-then-explodes" configurations.

**Steps.**

- **4.1 Multi-difficulty suite.** *Independent.* Add at least two more graduated problems at higher difficulty (e.g., `002_*` at difficulty 2, `003_*` at difficulty 3). TDD: suite loader yields all problems, sorted/groupable by difficulty.

- **4.2 Per-(problem, metric) events.** *Depends on Phase 2 ScoringPort.* Each trial's `events.jsonl` records one event per (problem, metric) pair, not aggregated. TDD: a multi-problem trial writes events for every problem.

- **4.3 Capability-profile aggregation.** *Depends on 4.2.* Lazy aggregation: take a trial's per-problem events and compute `(mean, p95, scaling_slope)` for each metric. Scaling slope = regression of `log(metric)` vs `difficulty`. TDD: known per-difficulty arrays produce hand-verified summaries.

- **4.4 Pareto frontier (3D).** *Depends on 4.3.* Extend Pareto computation to `(mean_cost, scaling_slope, mean_quality)`. TDD: a synthetic trial set demonstrates that a high-slope cheap configuration is not dominated by a low-slope moderate one.

- **4.5 Acceptance test.** *Depends on 4.4.* Construct a configuration we know will scale poorly (e.g., a small model that fails on hard problems); confirm `scaling_slope` captures it and the frontier ranks accordingly.

**Interface-review checkpoint.** Before Phase 5:
- Should capability-profile aggregation be a `MetricAggregatorPort`, or stay an inline computation? Phase 1 already has a private `TrialRunner._aggregate` helper — Phase 4 must decide: lift it to a port, generalize it inline for fibered metrics, or replace it altogether.
- Are the chosen summary axes the right ones, or does v1 evidence point at different/additional axes?
- Does the scaling-slope regression behave reasonably with sparse difficulty coverage?
- All assertions on aggregated rate/quality must use `pytest.approx` (Phase 1 hit float-precision drift on `mean([0.8, 0.8, 0.8])`).

---

## Phase 5 — Subjective scoring (async, partial)

**Goal.** Subjective scores arrive after a trial closes, retroactively update `final.json`, and the optimizer tolerates partially-scored trials.

**Deliverable.** A `pi-eval score` CLI accepts a trial id and a subjective rating, appends a subjective-score event, and atomically updates `final.json`. The optimizer runs correctly with a mix of fully-scored and partially-scored trials in history.

**Steps.**

- **5.1 Subjective-score event schema.** *Independent.* Define the event shape (trial id, score, optional notes, timestamp, scorer identity). TDD: serialization round-trip.

- **5.2 Append-and-finalize.** *Depends on 5.1.* Phase 1's `PersistencePort.finalize_trial(trial_id, final_metrics, subjective_score=None)` closes a trial in one shot at objective-scoring time. Phase 5 adds either a new port method `update_subjective_score(trial_id, score)` or explicit re-finalize semantics — pick during 5.2 RFD. The CLI appends a subjective-score event to `events.jsonl` and atomically rewrites `final.json` (write-temp + rename, matching the existing pattern). TDD: concurrent append safety; idempotent re-application; no recomputation of objective metrics on subjective updates.

- **5.3 Partial-score policy.** *Depends on Phase 4.* Optimizer reads a partial trial as having `subjective = None`. Define an explicit policy: missing subjective is excluded from any axis that depends on it (rather than imputed). TDD: a history mix produces a Pareto frontier that includes partially-scored trials in axes that don't require subjective.

- **5.4 Acceptance test.** *Depends on 5.3.* Run a trial → optimizer makes a decision based on objective only → user later appends a subjective score → next round reflects the now-complete trial.

**Interface-review checkpoint.** Before Phase 6:
- Is the partial-score policy (exclude vs. impute) the right default, or should it be per-deployment-scenario configurable?
- Does the retroactive-update mechanism scale toward enterprise volumes (anticipating future)?
- Is the subjective-score CLI ergonomic enough for the individual scenario when it lands as an adapter?

---

## Phase 6 — Surrogate model and acquisition

**Goal.** The optimizer uses past trials to predict and select the next configuration, replacing random sampling with directed proposal.

**Deliverable.** Given an initial random-design seed of trials, the surrogate model directs subsequent proposals toward Pareto-improving configurations within a fixed budget.

**Steps.**

- **6.1 Featurize Package.** *Independent.* Map a `Package` to a feature vector suitable for the surrogate. TDD: identical packages yield identical features; semantically distinct packages yield distinct features.

- **6.2 Surrogate model.** *Depends on 6.1.* Start with a simple Gaussian Process over the feature vector predicting `(mean_cost, mean_quality, scaling_slope)`. TDD: trained on a known function, the surrogate predicts within tolerance on held-out points.

- **6.3 Acquisition function.** *Depends on 6.2.* Expected hypervolume improvement over the Pareto frontier (or simpler scalarized expected-improvement at first). TDD: on a synthetic problem with a known optimum, the acquisition function selects points biased toward the optimum.

- **6.4 SurrogateProposer.** *Depends on 6.3.* Replace `RandomFromSlotSpace` as the default proposer. TDD: on a synthetic problem, the surrogate-driven optimizer reaches a target Pareto frontier in fewer trials than random.

- **6.5 Acceptance test.** *Depends on 6.4.* End-to-end with real Pi, fixed budget; verify the optimizer's recommendations are stable across reruns and respect previously-evaluated identities.

**Interface-review checkpoint.** Closes the v1 loop. Surface any final wart in the abstractions before declaring v1 complete and writing v2 ADRs (multi-task GP, GNN over topologies, capability-profile-aware acquisition, etc.).

---

## What's deferred (not in v1)

Per the deployment-scenarios memory and the existing ADR backlog:

- **Workspace isolation strategy.** v1 uses tmpdir copy; future ADR.
- **Live-session sidecar adapter (individual scenario).** Future port adapter.
- **Fleet telemetry adapter (enterprise A/B).** Future port adapter.
- **SQL persistence backend.** Per ADR 0003 reconsider triggers.
- **Non-coding `GraduatedProblem` schemas.** Placeholder ADR pending.
- **Pareto-vector vs. scalarized quality.** Placeholder ADR pending; v1 uses 3D `(mean_cost, scaling_slope, mean_quality)`.
- **Multi-task GP / graph-kernel / GNN surrogates.** Phase 6 uses simple GP; richer surrogates land in v2.
- **Subjective-score elicitation UX.** Phase 5 ships a CLI; richer surfaces (IDE plugin, web form) belong to the individual-scenario adapter.
- **Explicit packaging surface (`__init__.py`, public re-exports).** Today the `pi_evaluator` tree relies on PEP 420 namespace packages — no `__init__.py` files exist and tests/imports resolve cleanly. Revisit when the `dev` and `deploy` mise tasks materialize: packaging the library for deployment to the Pi runtime may force explicit `__init__.py` files for build tools, runtime import-time validation, or a curated public surface (`from pi_evaluator import TrialRunner`).

---

## Ready to start?

The first piece of work is **Phase 1, Step 1.1** (domain types). Steps 1.1 and 1.2 can begin in parallel; after 1.1, steps 1.3–1.6 are independent of each other and can parallelize.
