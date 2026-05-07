# Title: 0005 - Trial Cost and Budget Model

**Status:** Proposed

*Spike in progress; decision target Phase 3.3 / 3.4.*

## Context

Pi reports per-message `usage` with both an integer `totalTokens` count and a structured `cost` field carrying input / output / cacheRead / cacheWrite dollar amounts plus a `total` (see Pi's `docs/session-format.md`). Phase 1 `Metrics` captured only `tokens_consumed`; Phase 2's `SyntheticSuiteScorer` sums `usage.totalTokens` across assistant `message_end` events. Three coupled questions are currently unresolved:

1. **Cost-tracking unit.** What does Phase 4's `mean_cost` Pareto axis measure: tokens, dollars, or both as separate axes? Token-cheap models (Gemini Flash) can be expensive in dollars under heavy use; dollar-cheap models can burn through tokens. The choice affects every downstream optimization signal — Pareto axes, surrogate features, budget enforcement.

2. **Per-trial cost cap.** Should the optimizer enforce a maximum cost per trial (e.g., kill the trial when its accumulated cost exceeds $X)? If yes, how is it enforced — by the optimizer driver polling Pi's running cost and aborting via signal, or by passing a cap into Pi? Pi has no built-in budget cap as of v0.73.0, so any enforcement is adapter-side.

3. **Project-level budget.** Should there be a cumulative cap across an optimization run (e.g., stop the optimizer after $20 total spent)? If yes, who tracks it — the optimizer driver, persistence, a separate budget tracker — and how is it persisted across restarts?

Phase 3.4 (optimizer driver) is the first place this matters: an unattended driver loop with no cost discipline can rack up real charges against the user's API key. The decision shapes the slot schema (does it include a `model_tier` slot?), the Pareto axes (3D vs. 4D vs. higher), the acquisition function's notion of "expected improvement per dollar," and the persistence layer (does `final.json` carry a cost field?).

## Options Considered

*To be developed during the spike. Initial sketches:*

### 1. Tokens only, no caps (status quo)

Phase 6 surrogate optimizes over `tokens_consumed` exclusively. Dollar costs are not surfaced. No per-trial or project-level budget enforcement.

* **Pros:** simplest; matches v1 implementation; tokens are deterministic given prompts.
* **Cons:** no cost protection for unattended runs; tokens-cheap-but-dollars-expensive configurations will be chosen by an optimizer that doesn't know dollars exist.

### 2. Dollars only, with per-trial cap

Track Pi's accumulated `cost.total`; abort trials that exceed a configured per-trial cap. Pareto axis switches from tokens to dollars.

* **Pros:** real-money signal in the optimizer; per-trial protection.
* **Cons:** dollar costs depend on provider pricing which can change; comparison across providers/models requires currency conversion (already handled by Pi); harder to reason about cache-hit-rate effects than raw tokens.

### 3. Both as separate Pareto axes

Track tokens AND dollars; report both; let Pareto frontier handle them as independent dimensions. Phase 4's "3D" frontier becomes 4D.

* **Pros:** preserves all information; lets the optimizer surface configurations that are interesting on either axis.
* **Cons:** more dimensions = harder for surrogates and humans; tokens and dollars are correlated, which dilutes Pareto-domination relationships; ADR 0006's reproducibility cost interacts.

### 4. Dollars with token-equivalent for normalization

Standardize all reporting to dollars but record token counts for explanatory diagnostics. Optimizer optimizes over dollars; tokens are reported alongside for human inspection.

* **Pros:** single optimization axis with the more meaningful unit; tokens still available in telemetry for debugging.
* **Cons:** requires currency conversion and handles cross-provider price drift implicitly.

## Decision

TBD — pending spike.

## Reconsider Triggers

TBD — will be filled in alongside the decision.

## Consequences

TBD — will be filled in alongside the decision.
