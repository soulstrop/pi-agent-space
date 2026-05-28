# Strategic Implementation Plan

This document defines the high-level roadmap for the `pi-agent-space` Python production code in `python/`. It outlines the phases and steps required to deliver the core functionality.

**Note:** This file is for strategic alignment and dependency tracking. **For tactical execution, task assignment, and daily workflow, use `bd` (beads) as defined in `AGENTS.md`.**

## Phase 1–3 Summary: Completed Foundations

*   **Phase 1: Single-trial smoke pipeline.** Established the Hexagonal architecture (Domain, Ports, Adapters). Defined core types (`Package`, `Trial`), candidate hashing, the 4-file persistence layout (`config.json`, `versions.json`, `events.jsonl`, `final.json`), and the `TrialRunner` orchestration over stub adapters.
*   **Phase 2: Real Pi execution.** Replaced stubs with real adapters: `CliSubprocessAdapter` (running Pi against tempdir-copied workspaces) and `SyntheticSuiteScorer` (deriving metrics from raw telemetry). Introduced validation execution and error classification.
*   **Phase 3: Multi-config search & basic Pareto.** Implemented the `OptimizerDriver` to run multiple configurations. Introduced a slot/value space schema, a `RandomFromSlotSpace` proposer, and calculated a 3D Pareto frontier (`tokens`, `dollars`, `quality`). Included cost caps and basic circuit breakers.

*The project is currently transitioning into Phase 4.*

---

## Phase 4 — Capability profile and scaling slope

**Goal.** Per-(problem, metric) records flow through the pipeline; trial-level metrics are derived as capability profiles; Pareto axes include the scaling slope.

**Deliverable.** Trials over a multi-difficulty suite produce capability profiles whose scaling slope distinguishes "uniformly moderate" from "cheap-then-explodes" configurations.

**Steps.**

- **4.1 Multi-difficulty suite.** Add at least two more graduated problems at higher difficulty (e.g., `002_*`, `003_*`).
- **4.2 Per-(problem, metric) events.** Each trial's `events.jsonl` records one event per `(problem, metric)` pair. Payload carries `(value, n_samples)`. Ensure `lifecycle.py` only handles telemetry-classified outcomes, while watchdogs handle `boundary_violation`.
- **4.3 Capability-profile aggregation.** Lazy aggregation of a trial's per-problem events into `(mean, variance, p95, n_samples, scaling_slope)`.
- **4.4 Pareto frontier (4D).** Extend Pareto computation to `(mean_tokens, mean_dollars, scaling_slope, mean_quality)`.
- **4.5 Acceptance test.** Construct a configuration known to scale poorly; confirm `scaling_slope` captures it.

---

## Phase 5 — Subjective scoring (async, partial)

**Goal.** Subjective scores arrive after a trial closes, retroactively update `final.json`, and the optimizer tolerates partially-scored trials.

**Deliverable.** A `pi-eval score` CLI accepts a trial id and a subjective rating, appends a subjective-score event, and atomically updates `final.json`.

**Steps.**

- **5.1 Subjective-score event schema.** Define the event shape.
- **5.2 Append-and-finalize.** Implement retroactive updates to `final.json` and `events.jsonl` for `"completed"` trials only. (Depends on resolution of open spikes 0009 and 0010).
- **5.3 Partial-score policy.** Define explicit policy: missing subjective is excluded from dependent axes.
- **5.4 Acceptance test.** Verify the optimizer loop handles the transition from objective-only to fully-scored trials.

---

## Phase 6 — Surrogate model and acquisition

**Goal.** The optimizer uses past trials to predict and select the next configuration via a surrogate model.

**Deliverable.** A surrogate model (Heteroscedastic GP) directs proposals toward Pareto-improving configurations.

**Steps.**

- **6.1 Featurize Package.** Map `Package` to a feature vector using the Phase 3.1 schema.
- **6.2 Surrogate model.** Implement `HeteroskedasticSingleTaskGP` over the feature vector. Enforce bootstrap discipline (pure exploration below ~10 trials).
- **6.3 Acquisition function.** Expected hypervolume improvement over the Pareto frontier (active only above bootstrap threshold).
- **6.4 SurrogateProposer.** Replace `RandomFromSlotSpace` as the default proposer.
- **6.5 Acceptance test.** End-to-end with real Pi, verifying stable, history-aware recommendations.

---

## Open spikes

| ADR | Question | Target phase | Status |
| --- | --- | --- | --- |
| 0009 (planned) | **Driver-run event log.** How to log per-run concerns (cost caps, circuit breakers) that cross trial boundaries? | Phase 5.2 | Open |
| 0010 (planned) | **Re-finalize semantics.** Does `finalized` need to be the absolute last event, affecting Phase 5 retroactive updates? | Phase 5.2 | Open |
| 0012 (planned) | **Boundary-violated trials visibility.** Should the surrogate see filtered boundary-violated trials as cliff signals? | Phase 6.2 | Open |

## What's deferred (not in v1)

- Stricter workspace isolation (containers).
- Live-session sidecar / Fleet telemetry adapters.
- SQL persistence backend.
- Non-coding schemas.
- Richer surrogate models (GNN, multi-task GP).
- Auto-detected `pi --version`.
- Tempdir cleanup hooks.