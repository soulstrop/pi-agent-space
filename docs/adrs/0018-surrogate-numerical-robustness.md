# Title: 0018 - Surrogate Numerical-Robustness Posture

**Status:** Proposed

> Spike in progress; the **independent-head fitting** decision (D3) targets **Phase 7**. D1 (float64) and D2 (Cholesky jitter) are adopted and implemented (`adapters/gp_numerics.py`); D3's Decision / Consequences read `TBD`.

## Context

ADR 0016 chose BoTorch/GPyTorch on PyTorch (CPU, float64) for the GP surrogate and EHVI acquisition. That ADR settled the *framework*; this one records the *numerical-robustness posture* the surrogate commits to for production — the kind of hardening that isn't a feature but is part of the surface we stand behind in v1 (Phase 7).

Two framing facts from ADR 0016 carry over and bound the decisions here:

- **The surrogate is not the bottleneck.** N = number of trials is in the tens-to-low-hundreds; GP fit and acquisition are sub-second against minutes-per-trial Pi runs. Numerical *robustness* matters; numerical *speed* essentially does not, at v1 scale.
- **Features are one-hot.** `domain/featurize.py` emits binary columns, and the ARD Matérn kernel assigns a lengthscale per column. Near-duplicate or collinear one-hot rows make the kernel matrix ill-conditioned, which is exactly where precision and Cholesky stability bite.

Three concerns surfaced in a production-readiness review.

## Decisions

### D1 — Mandate float64 across the surrogate and acquisition (Adopted)

Every tensor feeding the GP and the acquisition is constructed in float64. Implemented as a single gate, `gp_numerics.f64`, that both `HetGPSurrogate` and `EHVIAcquisition` route all tensor construction through, so a stray float32 cannot drift in. BoTorch itself warns when fed float32; double precision is the documented-stable path and the cost is negligible at our scale.

### D2 — Explicit Cholesky-jitter backstop (Adopted)

GPyTorch already adds baseline jitter before its Cholesky factorization (a probe with identical feature rows and near-zero noise did *not* raise — the built-in jitter plus the `MIN_NOISE_VAR` floor absorbed it). D2 is therefore **defense-in-depth, not a fix for a reproducible crash**: `gp_numerics.cholesky_safe` wraps GP fit, posterior, and acquisition scoring in an *escalating* jitter schedule (`1e-8 → 1e-6 → 1e-4`) and, if even the largest nudge fails, raises a clear `SurrogateNumericalError` naming the operation instead of letting an opaque `NotPSDError` / `LinAlgError` surface deep in a posterior call. This makes the jitter posture explicit and tunable and gives operators a legible failure.

### D3 — Independent-head fitting strategy (Open; decision target Phase 7)

Today `HetGPSurrogate.fit` is a sequential per-axis loop: one `SingleTaskGP` + `ExactMarginalLogLikelihood` + `fit_gpytorch_mll` per Pareto axis. The question: should the heads be fit **in parallel** by batching them into a single multi-output model?

The relevant structural fact: the **four objective heads share identical `train_X` by construction** (`build_training_data` appends the same encoded row to all four for every eligible trial), so they could become one batched multi-output `SingleTaskGP` whose marginal log-likelihoods are optimized together in a single `fit_gpytorch_mll` call. The sparse `subjective` head has different support and is already excluded from the acquisition frontier, so it would stay a separate head.

Decision: TBD. See Options.

## Options for D3

### 3a. Status quo — sequential per-axis `SingleTaskGP` loop
* **Pros:** Simplest; uniform treatment of all five heads; trivially handles the heterogeneous `subjective` support. Already shipped and tested.
* **Cons:** Not "parallel" in the PyTorch-vectorized sense — five separate fits. Leaves the independent-heads structure expressed as a Python loop.

### 3b. Batched multi-output GP for the four objective heads (+ separate `subjective`)
* **Pros:** Genuine parallel LML optimization across the four shared-`train_X` heads via one batched fit. Likely lets `EHVIAcquisition` consume that single multi-output model directly, **dropping the `ModelListGP` assembly** and simplifying the surrogate↔acquisition seam. Idiomatic BoTorch.
* **Cons:** Revisits ADR 0016's "5 independent heads" framing. Restructures `fit`, the `models` interface EHVI reads, and per-axis `train_Yvar` handling; `subjective` becomes a special case rather than a uniform head. **Negligible wall-clock payoff at v1 scale** (the surrogate is not the bottleneck) — the value is structural, not performance.

## Consequences

D1/D2: tensor construction and factorizing calls are centralized in `gp_numerics`; `SurrogateNumericalError` joins `SurrogateNotFittedError` as the surrogate's typed failure modes. D3: TBD.

## Reconsider Triggers

- A realistic workload makes surrogate fit time non-negligible (would raise D3's priority and flip the speed argument).
- Frontier dimensionality grows (per-role axes) such that a batched model's structure materially simplifies the acquisition.
- A Cholesky failure escapes the jitter schedule in practice (would prompt revisiting the schedule, the noise floor, or input de-duplication).

## Related

- ADR 0016 (surrogate framework) — D3 revisits its "5 independent heads" structure.
- `pi-agent-space-3kz` — the production-readiness review that surfaced D1–D3.
- `adapters/gp_numerics.py` — implementation of D1/D2.
