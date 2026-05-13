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

**Phase 2 outcomes feeding later phases.**

- The Pi invocation pattern is fixed: `pi --print --no-session --mode json --model <provider/id> --system-prompt <text> --tools <csv> "<prompt>"`. Recorded in `docs/design-notes.md`. Phase 6 featurization assumes this shape.
- `package.skills` values are passed verbatim to Pi's `--tools` flag. Slot-space schemas in Phase 3.1 must enumerate valid Pi tool names (built-ins: `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`) and decide how to handle extension-installed tools. **Pi treats `--tools` as order-insensitive** (verified against 0.74), so `Package.skills` is set-valued at the semantic level. The candidate-identity hash canonicalizes by sorting before hashing; the field stays `list[str]` for JSON-serialization stability.
- Pi's `usage` field carries both `totalTokens` and a per-call `cost` in dollars. v1 surfaces only `tokens_consumed` so far; **ADR 0005 commits to tracking both as separate Pareto axes**. `Metrics` extends with `cost_dollars: float`; `SyntheticSuiteScorer` extracts `usage.cost.total` alongside `totalTokens`. Phase 4's frontier becomes 4D (tokens, dollars, scaling slope, quality), 5D once subjective lands. The optimizer driver gains `per_trial_cost_cap_usd` and `per_run_cost_cap_usd` parameters (defaults `None`); enforcement is a watchdog with two thresholds (warning + hard stop), mechanism deferred to design-notes when implemented.
- `subprocess.run` with no timeout is the v1 invocation. **ADR 0007 commits to:** A2 source-of-kill classification (timeouts count as boundary violations); B1 adapter-layer retries with default `N=2` against the same materialized workspace; persistent errors **preserve the trial's workspace + telemetry + stderr on disk** and queue for asynchronous human classification (no auto-re-propose by the driver); a circuit breaker on the driver halts the run when consecutive errored trials exceed a threshold OR wall-clock without a completed trial exceeds T. New trial event phases land: `error_retry`, `error_escalated`, `boundary_violation`. The `finalized` event payload gains an `outcome: "completed" | "boundary_violation" | "error_escalated"` field. **Phase 2 closeout landed:** `RawTelemetry.stderr` and `RawTelemetry.malformed_lines` (no more silent dropping); `Trial.outcome` + `final.json["outcome"]` + `finalized` event payload `outcome` field; `TrialRunner._classify_outcome` (any non-zero exit code or any assistant `message_end` with `stopReason == "error"` → `error_escalated`). **Still owed by Phase 3.4:** subprocess timeout, retry budget (`N=2`), persistent-error preservation queue, and the subprocess-timeout `boundary_violation` trigger (cost-cap triggers and the consecutive-errors / time-without-completed circuit breaker are wired).
- LLM outputs are non-deterministic. **ADR 0006 commits to** a heteroscedastic GP single-shot default; switchable fixed-N replicates opt-in per deployment scenario (R&D synthetic and individual default to `replicates=1`; enterprise A/B configures `replicates ≥ 3`). The HetGP needs ~10–20 samples to fit reliably — below the **bootstrap threshold** (default 10) acquisition uses pure exploration without weighting the surrogate's mean. The HetGP sees `boundary_violation` trials as data points (negative signal teaching the cost cliff) but does **not** see `error_escalated` trials until a human classifies them.
- `GraduatedProblemSetAdapter` loads every `problem.json` in its base dir. Once Phase 4.1 lands 002+ problems, the Phase 2.5 and any future single-problem acceptance tests will iterate the whole suite on real Pi — slow and costly. The adapter (or its callers) needs a `problem_ids: list[str] | None` filter or a tmpdir-copied subset before 002 lands.

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

- **2.1 Workspace materialization helper.** *Independent.* Copy `GraduatedProblem.workspace_dir` into a temp directory the trial can mutate; return the temp path. **v1 isolation strategy: tmpdir copy per ADR 0004.** Per Phase 1's contract, materialization is invoked by the harness adapter, not by `TrialRunner` — the runner continues to pass `problem.workspace_dir` through unchanged.

- **2.2 CliSubprocessAdapter.** *Depends on 2.1.* Spawn Pi as a subprocess against the materialized workspace, with the package's prompt/system-prompt/template-values surfaced via Pi's CLI flags or a generated `pi.json`. The adapter calls the workspace helper from 2.1 internally before spawning Pi. Capture Pi's stdout event stream and exit code into `RawTelemetry`. TDD: a fixture mocking Pi (a tiny script standing in) verifies the adapter parses the event stream and returns the expected `RawTelemetry`.

- **2.3 Validation execution.** *Depends on 2.2.* After Pi finishes, run each `ValidationStep.command` in the materialized workspace; capture exit codes. **Extends `RawTelemetry`** with a `validation_results: list[ValidationResult]` field carrying `(step_name, exit_code, stdout, stderr)` per step, so scoring stays a pure function of telemetry. TDD: validation against a workspace where the agent succeeded and one where it failed.

- **2.4 Real `SyntheticSuiteScorer`.** *Depends on 2.2, 2.3.* Derive `tokens_consumed` from Pi telemetry, `validation_pass_rate` from `RawTelemetry.validation_results` exit codes, `quality_score` as a simple synthetic (e.g., validation pass rate × 1.0 — intentionally minimal in v1; weights and additional axes land in their own ADR). Per-trial cross-problem aggregation continues to live in `TrialRunner._aggregate`; the scorer is per-(telemetry → metrics) only. TDD: known telemetry → expected metrics.

- **2.5 Acceptance test.** *Depends on 2.4 + Phase 1.7.* End-to-end with real Pi, the v0 baseline package (gemini-flash + supplied system prompt + Read/Write/Edit/Bash tool subset), single graduated problem; assert the trial directory contains real metrics from a real run. Requires Pi installed; document under a contributors-guide note.

**Interface-review checkpoint.** Before Phase 3:
- Is `RawTelemetry` a stable shape across Pi versions, or does drift in Pi's CLI/event-stream surface require versioning?
- Does the adapter cleanly handle Pi failures (timeout, crash, malformed events)?
- Are any of ADR 0004's reconsider triggers (concurrent trials, untrusted problems, observed resource leaks) firing under Phase 3's multi-trial cadence? If yes, draft a successor ADR before depending on tmpdir-copy semantics that may be about to change.
- Did the package configuration shape survive contact with Pi's actual CLI surface?

---

## Phase 3 — Multi-config search, random proposer, basic Pareto

**Goal.** Run multiple package configurations against the suite, persist all trials, and compute a Pareto frontier from history. No surrogate model yet — random proposer over a declared slot space.

**Deliverable.** Running the optimizer produces N trial directories and a Pareto frontier output identifying the non-dominated configurations.

**Steps.**

- **3.1 Slot/value space schema.** *Independent.* Declare slots and candidate values (the v0 baseline + at least one alternative per slot per the seed-variations decision). Slots include `model` (provider/id strings — pick a small enum from Pi's supported providers), `skills` (subset of Pi's built-in tool names from Phase 2), `system_prompt` (variant catalog), `template_values` (per Phase 1.3 plan-refinement). Each value carries the `(role, type)` tag from the Bockeler distinction. **Validate skill values against Pi's tool list** so a proposed package can actually run. TDD: enumerating the space yields the expected Cartesian product (or sampled subset); invalid skill names are rejected at schema-load time.

- **3.2 RandomFromSlotSpace proposer.** *Depends on 3.1.* `propose(history) -> Package` as uniform random over the declared space, excluding configurations already evaluated (by candidate-identity from 1.2). TDD: with mocked history, proposer skips already-evaluated identities; without history, samples freely.

- **3.3 Pareto frontier (3D).** *Independent.* Compute the Pareto frontier over `(mean_tokens, mean_dollars, mean_quality)` from a list of trials. **Both cost axes per ADR 0005** — tokens and dollars are kept separate because token-cheap can be dollar-expensive and vice versa. TDD: hand-verified frontier members on a known trial set, including a config that dominates on tokens but loses on dollars (and vice versa).

- **3.4 Optimizer driver.** *Depends on 3.2, 3.3, Phase 2.* Loop: load history → propose → run trial → persist → recompute frontier. Bounded by a trial budget and by the cost caps below. The driver gains the following configuration parameters with non-disruptive defaults:
    - `per_trial_cost_cap_usd: float | None = None` and `per_run_cost_cap_usd: float | None = None` (ADR 0005); enforcement watchdog with warning + hard-stop thresholds.
    - `replicates: int = 1` (ADR 0006); `>1` triggers fixed-N replication of `(package, problem)` pairs.
    - `bootstrap_threshold: int = 10` (ADR 0006); below this trial count, acquisition uses pure exploration; above, transitions to GP-driven.
    - `max_consecutive_errors: int` and `max_time_without_completed_trial: timedelta` (ADR 0007); circuit-breaker thresholds that halt the run gracefully.
    - Adapter-layer retry budget for transient errors (`N=2` default, ADR 0007); persistent errors preserve the trial directory and tag the trial `error_escalated` for asynchronous human classification — the driver does not auto-re-propose. The adapter-side outcome classifier already lands in Phase 2 closeout (exit-code or assistant `stopReason == "error"` → `error_escalated`); Phase 3.4 extends it with the `boundary_violation` triggers (timeouts, cost-cap breaches) and wires retry/preservation/circuit-breaker around the existing `Outcome` value.

  TDD: with a stub harness returning deterministic metrics by config, the driver produces the expected frontier within budget; cost caps trigger boundary-violation trials with `quality_score=0` and real `cost_dollars`; the circuit breaker halts the run when its thresholds are crossed; persistent errors land in the preservation queue without progressing as fresh trials.

- **3.5 Acceptance test.** *Depends on 3.4.* Run the optimizer against the real Pi for a small budget (~4–6 trials) over the slot space; assert all trials persist and a frontier file is generated. **This is a driver-mechanics test, not a meaningful surrogate-quality test** — per ADR 0006, fewer than ~10 trials sit below the bootstrap threshold, so the optimizer behaves like random search. Filter `GraduatedProblemSetAdapter` to a fixed problem-ID list so the test is stable when 002+ land.

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

- **4.1 Multi-difficulty suite.** *Independent.* Add at least two more graduated problems at higher difficulty (e.g., `002_*` at difficulty 2, `003_*` at difficulty 3). TDD: suite loader yields all problems, sorted/groupable by difficulty. **Update Phase 2.5 and Phase 3.5 acceptance tests to filter to a stable single-problem subset** so they don't iterate the whole suite on every real-Pi run.

- **4.2 Per-(problem, metric) events.** *Depends on Phase 2 ScoringPort.* Each trial's `events.jsonl` records one event per `(problem, metric)` pair, not aggregated. **Per-pair payload carries `(value, n_samples)` per ADR 0006** — `n_samples=1` under the single-shot default, `n_samples > 1` only when `replicates > 1`. Cost is two values per trial (`tokens`, `dollars`) per ADR 0005. The lifecycle event phases from ADR 0007 (`error_retry`, `error_escalated`, `boundary_violation`) ride alongside the per-(problem, metric) events. TDD: a multi-problem trial writes events for every problem; `replicates > 1` runs accumulate matching `n_samples`; a boundary-violated trial emits the matching lifecycle phase.

- **4.3 Capability-profile aggregation.** *Depends on 4.2.* Lazy aggregation: take a trial's per-problem events and compute `(mean, variance, p95, n_samples, scaling_slope)` for each metric. Variance and `n_samples` per ADR 0006 — they ride along even under the single-shot default (variance = 0, n_samples = 1) so the surrogate's heteroscedastic noise model has data to fit when `replicates > 1` enters. Scaling slope = regression of `log(metric)` vs `difficulty`. TDD: known per-difficulty arrays produce hand-verified summaries; replicated runs aggregate correctly across replicates and across difficulty levels.

- **4.4 Pareto frontier (4D).** *Depends on 4.3.* Extend Pareto computation to `(mean_tokens, mean_dollars, scaling_slope, mean_quality)` per ADR 0005. With Phase 5's subjective scoring, the frontier becomes 5D. TDD: a synthetic trial set demonstrates that a high-slope cheap configuration is not dominated by a low-slope moderate one; a token-cheap-but-dollar-expensive configuration sits on the frontier alongside its mirror.

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

- **5.2 Append-and-finalize.** *Depends on 5.1.* Phase 1's `PersistencePort.finalize_trial(trial_id, final_metrics, subjective_score=None)` closes a trial in one shot at objective-scoring time. Phase 5 adds either a new port method `update_subjective_score(trial_id, score)` or explicit re-finalize semantics — pick during 5.2 RFD. The CLI appends a subjective-score event to `events.jsonl` and atomically rewrites `final.json` (write-temp + rename, matching the existing pattern). **Subjective scoring applies only to trials whose `outcome` is `"completed"` (ADR 0007)** — boundary-violated and error-escalated trials don't receive subjective scores; the CLI rejects attempts to score them. TDD: concurrent append safety; idempotent re-application; no recomputation of objective metrics on subjective updates; rejection of subjective-score attempts on non-completed trials.

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

- **6.1 Featurize Package.** *Independent.* Map a `Package` to a feature vector suitable for the surrogate. **Featurization piggy-backs on the Phase 3.1 slot/value schema** rather than treating Package as raw text — provider/id strings, free-text system prompts, and arbitrary skills lists are too high-dimensional otherwise. The surrogate's *output* space is the Phase 4.4 Pareto axes: `(mean_tokens, mean_dollars, scaling_slope, mean_quality)`, plus subjective once Phase 5 lands. TDD: identical packages yield identical features; semantically distinct packages yield distinct features.

- **6.2 Surrogate model.** *Depends on 6.1.* **Heteroscedastic Gaussian Process per ADR 0006** — `HeteroskedasticSingleTaskGP` from BoTorch (or equivalent) over the feature vector predicting the 4D output (5D with subjective). The HetGP models input-dependent variance; the trial event stream's `(value, n_samples)` payloads from Phase 4.2 feed the noise model. **Bootstrap discipline** per ADR 0006: below ~10 trials the surrogate is unreliable, so acquisition (Step 6.3) ignores its mean estimate. TDD: trained on a known function, the surrogate predicts within tolerance on held-out points and reports calibrated variance estimates; bootstrap behavior under sparse training data matches spec.

- **6.3 Acquisition function.** *Depends on 6.2.* Expected hypervolume improvement over the Pareto frontier (or simpler scalarized expected-improvement at first). **Below the bootstrap threshold (ADR 0006), acquisition uses pure exploration** (Latin-hypercube or uniform random sampling within the slot space) instead of GP-driven proposals. Above the threshold, the standard EHVI path takes over. TDD: on a synthetic problem with a known optimum, the acquisition function selects points biased toward the optimum once past the bootstrap threshold; below the threshold, samples are uniformly distributed.

- **6.4 SurrogateProposer.** *Depends on 6.3.* Replace `RandomFromSlotSpace` as the default proposer. TDD: on a synthetic problem, the surrogate-driven optimizer reaches a target Pareto frontier in fewer trials than random *once past the bootstrap threshold* (the comparison below the threshold is meaningless since both are exploration).

- **6.5 Acceptance test.** *Depends on 6.4.* End-to-end with real Pi, fixed budget; verify the optimizer's recommendations are stable across reruns and respect previously-evaluated identities.

**Interface-review checkpoint.** Closes the v1 loop. Surface any final wart in the abstractions before declaring v1 complete and writing v2 ADRs (multi-task GP, GNN over topologies, capability-profile-aware acquisition, etc.).

---

## What's deferred (not in v1)

Per the deployment-scenarios memory and the existing ADR backlog:

- **Stricter workspace isolation (containers, namespace sandboxes).** v1 uses tmpdir copy per ADR 0004 (Accepted). Stricter isolation is gated on the reconsider triggers documented there: concurrent trials, untrusted problems, enterprise A/B, observed resource leaks, reproducibility-under-non-determinism.
- **Live-session sidecar adapter (individual scenario).** Future port adapter.
- **Fleet telemetry adapter (enterprise A/B).** Future port adapter.
- **SQL persistence backend.** Per ADR 0003 reconsider triggers.
- **Non-coding `GraduatedProblem` schemas.** Placeholder ADR pending.
- **Pareto-vector vs. scalarized quality.** Placeholder ADR pending; v1 uses 4D `(mean_tokens, mean_dollars, scaling_slope, mean_quality)` per ADR 0005, becoming 5D when subjective lands.
- **Multi-task GP / graph-kernel / GNN surrogates.** Phase 6 uses simple GP; richer surrogates land in v2.
- **Subjective-score elicitation UX.** Phase 5 ships a CLI; richer surfaces (IDE plugin, web form) belong to the individual-scenario adapter.
- **Explicit packaging surface (`__init__.py`, public re-exports).** Today the `pi_evaluator` tree relies on PEP 420 namespace packages — no `__init__.py` files exist and tests/imports resolve cleanly. Revisit when the `dev` and `deploy` mise tasks materialize: packaging the library for deployment to the Pi runtime may force explicit `__init__.py` files for build tools, runtime import-time validation, or a curated public surface (`from pi_evaluator import TrialRunner`).
- **Auto-detected `pi --version`.** `VersionVector.pi_version` is currently a hand-supplied label. The adapter should query Pi at construction or trial start and stamp the real version into the trial dir. Small fix; lands alongside Phase 3.4's other adapter touch-ups.
- **Tempdir cleanup hook.** `materialize_workspace` calls `tempfile.mkdtemp` and never cleans up; v1 trusts OS tmpdir reaping (`systemd-tmpfiles` or equivalent). Phase 3.4's multi-trial cadence × Phase 4.1's multi-problem suite will leave O(N×P) tempdirs per run — revisit if that becomes an observed leak under ADR 0004's reconsider triggers, or if the trial-preservation requirement for `error_escalated` (ADR 0007) needs the materialized workspace to outlive the trial.

---

## Open spikes

In-flight design spikes — tracked here so they don't get forgotten and so phase steps that depend on them have a clear pointer. Each entry resolves into an Accepted/Rejected ADR (or, for sub-ADR-weight findings, a `docs/design-notes.md` entry with the ADR Withdrawn). See [`docs/adrs/README.md`](adrs/README.md) for the spike workflow.

| ADR | Question | Target phase | Status |
| --- | --- | --- | --- |
| *(none open)* | | | |

When a spike closes, remove its row from this table; the ADR file remains as the durable record of the decision (or non-decision).

---

## Ready to start?

The first piece of work is **Phase 1, Step 1.1** (domain types). Steps 1.1 and 1.2 can begin in parallel; after 1.1, steps 1.3–1.6 are independent of each other and can parallelize.
