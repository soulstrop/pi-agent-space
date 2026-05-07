# Title: 0006 - Reproducibility Under Stochastic Agents

**Status:** Proposed

*Spike in progress; decision target Phase 3.4 / 6.2.*

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

TBD — pending spike.

## Reconsider Triggers

TBD — will be filled in alongside the decision.

## Consequences

TBD — will be filled in alongside the decision.
