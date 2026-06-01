# Title: 0016 - Numerical Framework for the Surrogate Model and Acquisition

**Status:** Accepted

## Context

Phase 6 replaces `RandomFromSlotSpace` with a surrogate-directed proposer: a Gaussian-process (GP) surrogate over the Phase 6.1 feature vector (ADR-adjacent; see `domain/featurize.py`), and an Expected Hypervolume Improvement (EHVI) acquisition function over the 5D Pareto frontier. The implementation plan (steps 6.2, 6.3) already names `HeteroskedasticSingleTaskGP` and EHVI — both BoTorch terms — but the framework choice was never written down as a decision, and it carries weight beyond Phase 6:

- The project currently has **zero runtime dependencies** (`python/pyproject.toml` declares `dependencies = []`). The surrogate framework is the first heavyweight runtime dependency we take on.
- That dependency directly determines the **containerization baseline** (torch vs. JAX vs. neither, CUDA or not), which is an open question we deliberately deferred until the GP library was chosen.
- The choice shapes how the rest of Phase 6 reads: which GP/kernel/acquisition primitives are off-the-shelf versus hand-rolled.

The decision this ADR closes: which numerical framework do we build the GP surrogate and EHVI acquisition on?

The crucial framing — and the thing that reorders the options — is that **Phase 6 is Gaussian-process / Bayesian-optimization work, not deep learning.** PyTorch, JAX, and Keras are tensor-and-autodiff substrates designed primarily for neural networks. The surrogate is not a neural net; it is an exact GP plus a hypervolume-based acquisition function. The decision should therefore be driven by which *Bayesian-optimization ecosystem* has the primitives we need, not by which tensor backend is fastest or most elegant.

A second framing fact: **the bottleneck in this system is running Pi against the eval suite** — minutes per trial, real API spend (see ADR 0010 on acceptance-test cost). GP inference is O(N³) in N = number of trials, and N is in the tens-to-low-hundreds range. The surrogate fit and acquisition optimization are sub-millisecond-to-millisecond operations, utterly negligible against the cost of producing the trials that feed them. No realistic v1 workload makes the surrogate the bottleneck.

## Options Considered

### 1. PyTorch via BoTorch + GPyTorch

BoTorch (built on GPyTorch, built on PyTorch) is the de facto standard for multi-objective Bayesian optimization in both research and industry.

* **Pros:**
  * Provides exactly the named primitives off the shelf: `SingleTaskGP` / `HeteroscedasticSingleTaskGP` with RBF-ARD kernels, `qExpectedHypervolumeImprovement`, `FastNondominatedPartitioning`, and `fit_gpytorch_mll` for the marginal-likelihood hyperparameter fit. Phase 6.2/6.3 become assembly of named parts, not machinery-building.
  * The error-prone part of EHVI — hypervolume box decomposition over the Pareto frontier — is a maintained, tested library component rather than our code.
  * Clean support for **observed-noise** GPs, which matters here: `domain/capability_profile.py` already computes per-metric `variance` across problems, so we have measured per-input noise. A fixed-observed-noise `SingleTaskGP` (noise varies per input but is supplied, not inferred) is far more numerically stable than the fully-learned `HeteroscedasticSingleTaskGP`, which has a finicky reputation in the BoTorch community. This lets us realize the "heteroscedastic" intent (input-dependent noise) without the unstable learned-noise machinery.
  * Runs on GPU unchanged if a future "really map the optimization space" workload ever justifies it — the door stays open without committing to it now.
* **Cons:**
  * torch is a large dependency (hundreds of MB), and it sets the container baseline. This is the real cost of entry.
  * Imperative / object-oriented style, which is less mathematically transparent than a functional formulation.

### 2. JAX (GPJax / TinyGP / NumPyro)

JAX is an excellent functional autodiff/JIT framework with a clean mathematical style and TPU/GPU support.

* **Pros:**
  * Functional purity maps elegantly onto the mathematical formulation in `docs/surrogate-model.tex` — a genuine aesthetic and conceptual fit for a project whose precursor is a categorical paper.
  * JIT, `vmap`, and TPU/GPU acceleration are first-class.
* **Cons:**
  * The JAX **Bayesian-optimization** ecosystem is thin. GPJax/TinyGP/NumPyro provide GPs, but there is no JAX equivalent of BoTorch's `qEHVI` + nondominated partitioning. We would hand-roll the hypervolume box decomposition — precisely the part most worth *not* reimplementing — or port it from BoTorch.
  * Every JAX performance advantage activates at scale we do not have. At N = tens-to-hundreds of trials, JIT/`vmap`/TPU optimize a cost that rounds to zero. The advantages are real but inert for this workload.

### 3. Keras 3 (multi-backend; PyTorch in dev, JAX in production)

Keras 3 offers backend-portable neural-network code across TensorFlow, PyTorch, and JAX.

* **Cons (decisive):**
  * Category error for this problem. Keras 3's portability is about neural-network *layers*; it has no GP surrogate and no EHVI acquisition. It would not abstract over GPyTorch-vs-GPJax (those are not Keras backends), so we would build the entire GP + acquisition stack from scratch underneath it and gain nothing.
  * The dev-PyTorch / prod-JAX split presupposes a meaningful performance gap worth a second implementation. Given that the surrogate compute is negligible against the cost of real Pi trials, this is two implementations, two dependency stacks, and double the test/drift surface for ~zero benefit.

### 4. Pure numpy / scipy

At our data scale, a fixed-noise GP plus EHVI is genuinely implementable without a heavyweight framework.

* **Pros:**
  * Preserves the project's near-zero-dependency posture and keeps the container baseline light — directly relevant to the deferred containerization decision.
  * Maximum transparency: the GP and acquisition math would live as readable numpy, appealing to the project's math-first ethos.
  * MLL hyperparameter optimization via `scipy.optimize` with numerical or hand-derived gradients is tractable at this N.
* **Cons:**
  * EHVI's hypervolume partitioning is subtle to implement correctly; a subtle bug there silently degrades every proposal the optimizer makes. This is exactly the machinery we would rather trust to a maintained library.
  * We would re-derive and re-test BO infrastructure that BoTorch already provides, spending Phase 6 effort on plumbing instead of on the optimizer's actual behavior.

## Decision

**Option 1 — PyTorch via BoTorch + GPyTorch.**

Rationale, in priority order:

1. **Ecosystem fit dominates.** This is GP/BO work, and BoTorch is the BO ecosystem. It hands us the exact primitives Phase 6.2/6.3 require — most importantly the tested hypervolume-partitioning machinery behind EHVI, which is the part we least want to author or maintain ourselves.
2. **The performance arguments for JAX are inert here.** The bottleneck is real Pi trials, not the surrogate. JIT/`vmap`/TPU/GPU optimize a cost that rounds to zero at v1 trial counts, so the framework's headline advantages do not pay off — while its ecosystem thinness for *multi-objective BO specifically* costs us real implementation work.
3. **We already have observed noise.** `capability_profile` computes per-metric variance, so we will start with a **fixed-observed-noise `SingleTaskGP`** (input-dependent but supplied noise) rather than the unstable learned-noise `HeteroscedasticSingleTaskGP`. This satisfies the heteroscedastic *intent* of `docs/surrogate-model.tex` (noise varies per input, and the subjective head's noise narrows as scores accrue) while avoiding the brittle path. Promotion to a fully-learned noise GP stays available if observed noise proves insufficient.
4. **GPU stays optional, not foreclosed.** BoTorch runs on GPU unchanged. If a future deep-exploration campaign ever justifies it, the path exists without a rewrite — but we are budget-constrained in v1 and will run on CPU.

On the functional-style preference (the genuine pull toward JAX, and the further pull toward Julia for its Category Theory DSL): acknowledged and real, but it is an aesthetic/conceptual fit argument, not a v1-value argument. The mathematical clarity lives in `docs/surrogate-model.tex` and the categorical precursor `docs/math.pdf` — the canonical Python implementation is permitted to be imperative without compromising that, per the precursor-consistency principle (precursors stay consistent *at their own abstraction level*, not detail-for-detail). We are choosing the framework that ships a correct optimizer soonest at v1 scale, and explicitly *not* choosing on elegance.

**Dependency placement.** torch/gpytorch/botorch enter as a runtime dependency of the Python package. The container baseline (deferred decision) is now: CPU-only torch, no CUDA, for v1.

## Reconsider Triggers

- **Scale changes the calculus.** If the optimization space grows to where surrogate fit/acquisition becomes a real wall-clock or budget cost (the deferred GNN / multi-task surrogates, or campaigns with thousands of trials and large discrete candidate sets), revisit GPU acceleration — first within BoTorch (free), and only then a different framework.
- **Observed noise proves insufficient.** If the fixed-observed-noise GP underfits the noise structure — e.g., the subjective head needs noise inferred at unobserved inputs — promote that head to a learned-noise model (within BoTorch first).
- **BoTorch's heteroscedastic/observed-noise APIs churn.** BoTorch has deprecated and reshaped noise-model classes before. If the specific class we depend on is removed, re-evaluate against the then-current BoTorch surface before reaching for a new framework.
- **Dependency weight becomes prohibitive.** If the torch footprint blocks a deployment target that genuinely matters (e.g., a constrained edge/CI environment where hundreds of MB is disqualifying), reconsider the pure-numpy/scipy fixed-noise GP — accepting the EHVI-correctness burden as the price of a light footprint.

## Consequences

- The Python package gains its first heavyweight runtime dependency: `botorch` (transitively `gpytorch`, `torch`, `scipy`). `python/pyproject.toml` moves from `dependencies = []` to a pinned BoTorch line.
- The deferred containerization decision is unblocked with a concrete baseline: CPU-only torch, no CUDA, for v1.
- Phase 6.2 implements the surrogate as one BoTorch `SingleTaskGP` per Pareto axis (5 independent heads), RBF-ARD kernel, fixed-observed-noise from the capability profile's per-metric variance, fit via `fit_gpytorch_mll`, behind a `SurrogateModelPort`. Bootstrap discipline (untrained below N₀≈10, falling back to random) lives in the proposer per ADR 0006.
- Phase 6.3 implements EHVI via BoTorch's `qExpectedHypervolumeImprovement` + nondominated partitioning over the 5D frontier; we do not author hypervolume decomposition.
- torch is imported lazily / behind the port so that the non-surrogate code paths and the existing unit suite do not pay import cost and remain runnable without torch where the GP is not exercised.
- JAX and Keras 3 are explicitly declined; this ADR is the breadcrumb for why, should the question resurface.
