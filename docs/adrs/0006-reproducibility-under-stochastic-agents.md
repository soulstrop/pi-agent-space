# Title: 0006 - Reproducibility Under Stochastic Agents

**Status:** Accepted

## Context

LLM outputs are non-deterministic. Two trials of the same `(package, problem)` pair will produce different telemetry — different tool calls, different token counts, possibly different validation results. The Bayesian optimization framework underlying this project assumes a mapping `(config, problem) → metrics` that the surrogate model can learn. If that mapping is noisy (which it is), the surrogate must either deal with the noise explicitly or risk treating a single noisy sample as ground truth.

Three coupled questions:

1. **Suppress vs. model the noise.** Can we reduce variance via deterministic API options — `temperature=0`, `seed=N`, `--thinking high|low` — enough that residual noise is negligible? Pi exposes some of these (e.g., `--thinking` levels, `--model X:high` thinking-level pinning); some providers expose `temperature` and `seed` natively, others don't. Coverage and effect size vary.

2. **Replicate vs. accept single-shot.** If suppression is incomplete (almost certainly), do we run each `(package, problem)` pair multiple times and average? If yes, **how many** — fixed N, adaptive based on observed variance, or budget-bounded? Replication multiplies cost (interacts with ADR 0005) and time (interacts with ADR 0007).

3. **Variance attribution.** Is the variance from the model (sampling), the harness (Pi's prompt construction or tool-call ordering), the validation environment (test runner timing, file-system race conditions), or the problem itself (ambiguous prompts that leave room for interpretation)? Each source has different mitigations.

This affects Phase 3.4 (does the driver run each proposal once or N times?), Phase 4.3 (capability profile assumes a per-(config, problem) point — is that a mean across replicates or a single sample?), and Phase 6.2 (the GP surrogate's noise model — homoscedastic, heteroscedastic, or per-config variance estimate).

## Options Considered

*To be developed during the spike. Initial sketches:*

### 1. Single-shot with seed/temperature suppression

Set whatever determinism knobs the model + Pi support, run each config once, treat residual noise as negligible.

* **Pros:** cheapest; simplest driver; no replication bookkeeping.
* **Cons:** residual noise in the observed metric becomes systematic surrogate error; coverage of seed/temperature options is provider-dependent and incomplete.

### 2. Fixed-N replicates per config

Always run each `(package, problem)` pair N times (e.g., N=3); aggregate by mean (and possibly variance). Surrogate sees `(config, mean_metric, variance)`.

* **Pros:** straightforward; gives the surrogate a noise estimate.
* **Cons:** N× cost and time per proposal; N is a guess that may be wrong (over-replicates easy configs, under-replicates noisy ones).

### 3. Adaptive replicates based on variance

Run a config once; if confidence interval is "tight enough" by some criterion, accept; else run again. Variant: budget-bounded (max k replicates).

* **Pros:** spends compute where it matters; converges to a bounded confidence interval.
* **Cons:** more complex driver; variance estimates from small samples are themselves noisy.

### 4. Heteroscedastic GP, single-shot

Run each config once; let the surrogate model `(config, problem) → metrics` as a noisy sample with input-dependent noise. The GP learns both mean and variance.

* **Pros:** statistically principled; no replication overhead; surrogate naturally weights uncertain points.
* **Cons:** harder to fit; needs more data than a deterministic GP; implementation complexity in Phase 6.2.

## Decision

The three sub-questions resolve as follows.

**1. Default noise model: option 4 — heteroscedastic GP, single-shot per `(config, problem)`.** The Phase 6.2 surrogate models `(config, problem) → metrics` as a noisy sample with input-dependent variance. The acquisition function trades exploration against exploitation using the GP's mean *and* variance: high-variance + high-promise regions get sampled to reduce uncertainty; high-variance + low-promise regions get skipped. Replication arises *organically* from acquisition — there is no explicit "run it N times" loop in v1.

**2. Switchable fallback: option 2 — fixed-N replicates, opt-in per deployment scenario.** The driver gains a `replicates: int = 1` parameter; values >1 trigger fixed-N replication, with the surrogate aggregating by mean (and variance, where N≥3). Mapping to the documented deployment scenarios:

- **R&D synthetic (v1 target):** `replicates = 1`. Tight trial budgets favor sample-efficient single-shot.
- **Individual:** `replicates = 1`. Single-user trial volume is too low for replication overhead to pay off.
- **Enterprise A/B:** `replicates ≥ 3`, configurable. Confidence intervals on per-config performance are part of the deliverable.

**3. Bootstrap discipline.** A heteroscedastic GP needs ~10–20 samples to fit reliably. Below that threshold the surrogate is bootstrapping and its mean estimate is unreliable. **Acquisition during bootstrap uses pure exploration** — Latin-hypercube sampling or uniform random within the slot space — without weighting the surrogate's mean. Above the threshold, acquisition transitions to GP-driven (Expected Hypervolume Improvement against the running Pareto frontier). The exact transition threshold is a Phase 6.2 hyperparameter; v1 starts at **10 trials**.

**Failed-trial metrics representation** — see ADR 0007. Aborted trials (timeout-as-boundary-violation, per the Phase 2 closeout discussion) record as data points the HetGP sees in feature space; the precise metrics shape for those points is owned by 0007. The framing this ADR commits to: failures are **signal, not loss** — the GP learns the cost / boundary cliff from them.

## Reconsider Triggers

- **Trust-region acquisition (TuRBO and similar)** if the surrogate's recommendations show high local variance in promising regions despite the heteroscedastic noise model. Trust-region BO restricts proposals to a neighborhood of best points rather than jumping to fresh regions, and is empirically helpful in noisy / high-dimensional settings — exactly our case. Document the intuition now; build it as a v2 acquisition refinement if the symptom appears.
- **Adaptive replication (option 3)** if fixed-N feels wasteful in practice — over-replicates easy configs, under-replicates noisy ones. SPRT or CI-bounded variants exist.
- **Multi-task GP** (cross-difficulty information sharing) if Phase 4's per-difficulty surrogates can't share information productively as separate models.
- **HetGP fitting becomes unstable** in the actual feature space (sparse data, high dimensionality, pathological covariance structure). Fall back to a deterministic GP with `replicates ≥ 3` (option 2) for robustness.
- **Failure modes don't cluster in feature space** — the GP fails to learn "don't go there" from failed trials, contradicting the ADR 0007 assumption. Forces a different failure-handling design (e.g., a separate classifier for feasibility).

## Consequences

- The Phase 6.2 surrogate is `HeteroskedasticSingleTaskGP` from BoTorch (or equivalent). Library choice is implementation detail; the policy commitment is heteroscedastic noise modeling.
- The optimizer driver gains two configuration parameters: `replicates: int = 1` and `bootstrap_threshold: int = 10`. Both have non-disruptive defaults — the existing Phase 1/2 single-trial flows are unaffected.
- **The HetGP's bootstrap requirement sets a floor on the smallest sensible v1 R&D trial budget.** Below ~10 trials, the optimizer behaves like random search regardless of how many slots we explore. This calibrates Phase 3.4's acceptance test framing — the small "4–6 trials" budget mentioned there is a *driver-mechanics* test, not a meaningful surrogate-quality test.
- Failed trials are signal, not loss: the HetGP sees them in feature space and learns where the cost / boundary cliff lives. ADR 0007 owns the metrics representation that makes this work.
- Per-config `(mean, variance, n_samples)` triples ride along in the trial event stream as forward-compatibility for adaptive replication or trust-region BO. `n_samples = 1` by default; `n_samples > 1` only when option 2 is in effect.
- Phase 4's capability profile aggregates these triples across difficulty levels rather than collapsing to a single mean.
