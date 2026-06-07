# Strategic Implementation Plan

This document defines the high-level roadmap for the `pi-agent-space` Python production code in `python/`. It outlines the phases and steps required to deliver the core functionality.

**Note:** This file is for strategic alignment and dependency tracking. **For tactical execution, task assignment, and daily workflow, use `bd` (beads) as defined in `AGENTS.md`.**

## Phase 1–3 Summary: Completed Foundations

*   **Phase 1: Single-trial smoke pipeline.** Established the Hexagonal architecture (Domain, Ports, Adapters). Defined core types (`Package`, `Trial`), candidate hashing, the 4-file persistence layout (`config.json`, `versions.json`, `events.jsonl`, `final.json`), and the `TrialRunner` orchestration over stub adapters.
*   **Phase 2: Real Pi execution.** Replaced stubs with real adapters: `CliSubprocessAdapter` (running Pi against tempdir-copied workspaces) and `SyntheticSuiteScorer` (deriving metrics from raw telemetry). Introduced validation execution and error classification.
*   **Phase 3: Multi-config search & basic Pareto.** Implemented the `OptimizerDriver` to run multiple configurations. Introduced a slot/value space schema, a `RandomFromSlotSpace` proposer, and calculated a 3D Pareto frontier (`tokens`, `dollars`, `quality`). Included cost caps and basic circuit breakers.

*Phases 4–6 are complete: the v1 tracer-bullet pipeline runs end to end, from real-Pi trials through capability profiles, subjective scoring, and a surrogate-directed proposer. The project is now in Phase 7 — production readiness — the final v1 phase, which establishes the surface (deployment, observability, security, schema/versioning, surrogate robustness) that v1 commits to (see below).*

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

**Goal.** Subjective scores arrive after a trial closes via an out-of-band CLI, and the optimizer tolerates partially-scored trials.

**Deliverable.** A `pi-eval score` CLI accepts a trial id and a subjective rating and writes a `subjective.json` sidecar alongside the trial's `final.json` (ADR 0014). `final.json` is objective-only; subjective data never mutates it.

**Steps.**

- **5.1 Subjective-score event schema.** Define the event shape.
- **5.2 Sidecar persistence.** `final.json` is objective-only. `write_subjective_score` writes a `subjective.json` sidecar for `completed` trials only (ADR 0007 §C1). `load_trials` reads the sidecar when present. `pi-eval score` CLI entry point.
- **5.3 Partial-score policy.** Define explicit policy: missing subjective is excluded from dependent axes.
- **5.4 Acceptance test.** Verify the optimizer loop handles the transition from objective-only to fully-scored trials. The Pareto frontier lifts from Phase 4's 4D `(mean_tokens, mean_dollars, scaling_slope, mean_quality)` to 5D with the subjective axis; partially-scored trials are excluded from dependent-axis dominance per 5.3.

---

## Phase 6 — Surrogate model and acquisition

**Goal.** The optimizer uses past trials to predict and select the next configuration via a surrogate model.

**Deliverable.** A surrogate model (Heteroscedastic GP) directs proposals toward Pareto-improving configurations.

**Steps.**

- **6.1 Featurize Package.** Map `Package` to a feature vector using the Phase 3.1 schema.
- **6.2 Surrogate model.** Implement `HeteroskedasticSingleTaskGP` over the feature vector. Output dimensionality matches the Pareto axes the acquisition function consumes — 5 heads (`mean_tokens`, `mean_dollars`, `scaling_slope`, `mean_quality`, `subjective`). Enforce bootstrap discipline (pure exploration below ~10 trials).
- **6.3 Acquisition function.** Expected hypervolume improvement over the Pareto frontier (active only above bootstrap threshold). EHVI computational cost grows with frontier dimensionality and trial count — 4D/5D over hundreds of trials is comfortable; if the frontier grows further (per-role axes, additional subjective dimensions), revisit.
- **6.4 SurrogateProposer.** Replace `RandomFromSlotSpace` as the default proposer.
- **6.5 Acceptance test.** End-to-end with real Pi, verifying stable, history-aware recommendations.

---

## Phase 7 — Production readiness (completes v1)

**Goal.** Phases 1–6 delivered the v1 tracer-bullet pipeline end to end. Phase 7 is the **final v1 phase**: not new optimizer features, but the production hardening that turns the pipeline into a surface we commit to. Drawing the v1 line *here* — rather than after Phase 6 — means the committed surface includes deployment, observability, security, schema/versioning, and surrogate-robustness guarantees, not just the happy-path algorithm.

**Deliverable.** A v1 that is deployable, observable, security-reviewed, and explicit about the on-disk/API surface it promises to keep stable.

**Workstreams (scope per stream settled at its spike/ADR):**

- **Containerization & deployment baseline.** Establish the runtime container posture (the torch baseline ADR 0016 deferred). Spike S006. Distinct from the stronger workspace-isolation containers still deferred below.
- **Observability suite.** Logging, tracing, and metrics as a coherent set, extending ADR 0015 (structured-logging depth). Spike S007.
- **Security pass & threat model.** [`docs/threat-model.md`](threat-model.md) and the v1 hardening scope (**ADR 0020**, Accepted): agent isolation (ADR 0009, done), persisted-secret redaction (v1), OS-level resource caps (v1), with egress/rotation/log-allowlist/validation-sandbox deferred to the enterprise scenario. Supply-chain hardening is enumerated here but owned by the containerization/CI workstreams. Spike S008 closed.
- **Schema governance & versioning.** The umbrella over the typed event-payload model (**ADR 0017**, Accepted) and the SemVer/compatibility policy (**ADR 0019**, Accepted): what schemas (package, eval-suite, event streams, persisted layouts) we govern, and what a version bump promises about reading data written by older versions. This is what makes "the committed surface" concrete.
- **Surrogate numerical-robustness posture.** ADR 0018 — float64 mandate and Cholesky-jitter backstop are done; the batched multi-output GP / parallel-head decision (spike S009) lands here.

---

## Open spikes

Spikes use a separate `S###` ID namespace so the planned-spike list and the ADR list never collide. When a spike is opened as a real ADR, fill in the ADR column; when the spike closes, remove the row.

| Spike | Question | Target phase | ADR (if opened) | Status |
| --- | --- | --- | --- | --- |
| S003 | **Boundary-violated trials visibility.** Should the surrogate see filtered boundary-violated trials as cliff signals? | Phase 6.2 | — | Open |
| S006 | **Containerization & deployment baseline.** What runtime container posture do we ship (the torch baseline ADR 0016 deferred)? | Phase 7 | — | Open |
| S007 | **Observability suite.** What logging/tracing/metrics surface do we commit to, extending ADR 0015? | Phase 7 | — | Open |
| S009 | **Batched multi-output GP.** Fit the 4 shared-`train_X` objective heads as one multi-output model (parallel LML, simpler EHVI seam)? Revisits ADR 0016. | Phase 7 | 0018 | Open |

## What's deferred (not in v1)

- Stricter workspace isolation (containers).
- Live-session sidecar / Fleet telemetry adapters.
- SQL persistence backend.
- Non-coding schemas.
- Richer surrogate models (GNN, multi-task GP).
- Auto-detected `pi --version`.
- Tempdir cleanup hooks.
