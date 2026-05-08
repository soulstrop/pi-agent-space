# Title: 0005 - Trial Cost and Budget Model

**Status:** Accepted

## Context

Pi reports per-message `usage` with both an integer `totalTokens` count and a structured `cost` field carrying input / output / cacheRead / cacheWrite dollar amounts plus a `total` (see Pi's `docs/session-format.md`). Phase 1 `Metrics` captured only `tokens_consumed`; Phase 2's `SyntheticSuiteScorer` sums `usage.totalTokens` across assistant `message_end` events. Three coupled questions were unresolved:

1. **Cost-tracking unit.** What does Phase 4's `mean_cost` Pareto axis measure: tokens, dollars, or both as separate axes? Token-cheap models (Gemini Flash) can be expensive in dollars under heavy use; dollar-cheap models can burn through tokens. The choice affects every downstream optimization signal — Pareto axes, surrogate features, budget enforcement.

2. **Per-trial cost cap.** Should the optimizer enforce a maximum cost per trial (e.g., kill the trial when its accumulated cost exceeds $X)? If yes, how is it enforced — by the optimizer driver polling Pi's running cost and aborting via signal, or by passing a cap into Pi? Pi has no built-in budget cap as of v0.73.0, so any enforcement is adapter-side.

3. **Project-level budget.** Should there be a cumulative cap across an optimization run (e.g., stop the optimizer after $20 total spent)? If yes, who tracks it — the optimizer driver, persistence, a separate budget tracker — and how is it persisted across restarts?

Phase 3.4 (optimizer driver) is the first place this matters: an unattended driver loop with no cost discipline can rack up real charges against the user's API key. The decision shapes the slot schema (does it include a `model_tier` slot?), the Pareto axes (3D vs. 4D vs. higher), the acquisition function's notion of "expected improvement per dollar," and the persistence layer (does `final.json` carry a cost field?).

### Motivating scenario

The case that forces this discussion sharper than any single-agent setup is the **mixed-squad workflow**, where a package wires several LLM-backed roles together in a DAG: e.g., an *Architect* that produces a modular decomposition of a problem with per-module completion gates; one or more *Developer* agents that implement modules and submit pull requests; a *Tester* agent that, from a separate context, evaluates implementations against the gates and accepts or rejects each PR; a *Librarian* agent that maintains documentation–implementation alignment and surfaces drift to the Architect or human. The cycle repeats until all features pass all gates.

Each role can be assigned a different model. A central optimization path is searching over role-to-model assignments to find the cheapest workflow that meets the gates. *Cheap* is environment-dependent: in some settings tokens are the limiting factor (rate limits, context windows, free-tier caps); in others, dollars dominate (per-project budgets, monthly caps). Models that are token-cheap can be dollar-expensive and vice versa, so collapsing both into one number throws away exactly the information the operator needs to pick the right workflow for their constraint.

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

The three questions resolve as follows.

**1. Cost-tracking unit: option 3 — both tokens and dollars as separate Pareto axes.** `Metrics` extends with `cost_dollars: float` alongside `tokens_consumed: int`. Phase 4's `mean_cost` becomes two axes (`mean_tokens`, `mean_dollars`); the Phase 4 frontier is therefore 4D rather than 3D, and 5D once subjective scoring lands. The mixed-squad scenario above is the case that forces this — neither axis alone preserves the operator's ability to choose under a different limiting factor.

For optimization signal purposes, a trial's two cost numbers are *totals across all role-invocations*; per-role attribution is not part of the optimization signal in v1. Telemetry events MAY carry per-role tags so post-hoc analysis can break down where cost went, but the optimizer's surrogate sees aggregates only. Adding per-role attribution to the optimization signal is a future refinement (see Reconsider Triggers).

**2. Per-trial cost cap: yes, settable, dollars only.** The driver gets a configurable per-trial cap expressed in dollars. The dollar axis is what realistically matters for budget protection — token counts can be high in cheap models without meaningful financial impact, and a per-trial token cap would need to vary by model to stay meaningful. A single dollar cap applies uniformly across providers.

**3. Per-run cost cap: yes, settable, dollars only.** The driver also gets a configurable per-optimization-run cap (i.e., per `mise run optimize` invocation). Persisted state across restarts is out of scope for v1 — caps reset when a run begins. Lifetime/monthly project budgets are an operator concern outside the optimizer code.

**4. Cap enforcement mechanism: deferred to implementation.** Three plausible mechanisms exist (driver-side polling of Pi's accumulated cost, an external watchdog process, a future Pi flag) and each has different latency, accuracy, and cleanup-on-abort properties. The right choice will be apparent once Phase 3.4 starts and the integration shape is concrete. The expected pattern is **two thresholds**: a soft *warning* point that emits a structured event without aborting, and a hard *stop* point that aborts the trial (per-trial cap) or halts the driver (per-run cap). When the mechanism is chosen, the rationale lands in `docs/design-notes.md`.

## Reconsider Triggers

- **Provider pricing shifts** materially change the token-to-dollar ratio across the slot space, making the surrogate's correlation assumptions stale.
- **Per-role cost attribution becomes load-bearing** for the surrogate (e.g., for credit assignment in Phase 6), forcing the optimization signal to grow from totals to per-role breakdowns.
- **Per-trial caps prove insufficient** because trials need finer-grained caps (per-phase, per-step, per-role) — e.g., the Tester role keeps blowing through budget while the Architect under-spends.
- **Pi gains a built-in cost cap** in a future release, superseding the driver-side enforcement choice.
- **Compliance / audit requirements** force dollar-only tracking or a different cap granularity (e.g., per-organization rather than per-run).
- **A v2 surrogate model** that explicitly exploits the token/dollar correlation would change the case for keeping them as separate axes.

## Consequences

- `Metrics` extends with `cost_dollars: float`. `SyntheticSuiteScorer` extracts `usage.cost.total` from assistant `message_end` events alongside `totalTokens`. `final.json` carries both.
- Phase 4's Pareto frontier is 4D (`mean_tokens`, `mean_dollars`, `scaling_slope`, `mean_quality`); 5D once subjective scoring lands. Frontier-selection UX in human-facing tooling will need reduced-axis projections (e.g., 2D slices conditioned on the third axis) to stay legible. This is a UX/reporting concern, not an optimizer concern — the surrogate handles the high-D space natively.
- The surrogate has more axes to fit, which raises the sample-efficiency bar. Coupled with ADR 0006's replication question: how many trials we need scales with how many axes carry meaningful variance.
- The optimizer driver gains two configuration parameters: `per_trial_cost_cap_usd: float | None` and `per_run_cost_cap_usd: float | None`. Both default to "no cap" so existing single-trial usage is unchanged; the Phase 3.4 acceptance test exercises the cap path.
- The persistence layer adds a cost field to `final.json`. Trial directory layout is otherwise unchanged.
- Per-role cost attribution is a non-blocker for v1 optimization. We don't need to design role-aware telemetry now; we just need the door open. The trial event-stream model already permits per-event payload tags, so future per-role attribution is additive.
- Cap-enforcement mechanism stays as a known unknown until Phase 3.4 implementation begins. The decision will be documented in `docs/design-notes.md` when it lands; the policy commitments above (caps exist, they're in dollars, two thresholds) are stable regardless of mechanism.
