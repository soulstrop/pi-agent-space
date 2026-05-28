# Title: 0012 - Capability Profile and Per-(Problem, Metric) Events

**Status:** Accepted

## Context

Phase 4 of the implementation plan (`docs/implementation-plan.md`) turns the
trial pipeline from "one aggregate `Metrics` per trial" into "a capability
profile derived from per-problem records," and lifts the Pareto frontier to
4D `(mean_tokens, mean_dollars, scaling_slope, mean_quality)` per ADR 0005's
closing commitment. Three coupled questions surface at once:

1. **Event payload shape (step 4.2).** The plan says "each trial's
   `events.jsonl` records one event per `(problem, metric)` pair. Payload
   carries `(value, n_samples)`." Today `TrialRunner` emits two events per
   problem — `eval` (with `exit_code`) and `scored_objective` (with all four
   metric values bundled). Three structural readings are open:

   - Replace `scored_objective` with N independent `metric_record` events,
     one per `(problem, metric_name)` pair.
   - Keep `scored_objective` as a per-problem summary AND emit metric_record
     events alongside it.
   - Extend `scored_objective`'s payload to carry `{metric_name: (value,
     n_samples)}`, leaving event cardinality unchanged.

   Downstream consumers (CapabilityProfile aggregator, Phase 6 surrogate
   feature extraction, Phase 5 subjective-score retrofits) read this shape;
   commit early so they share assumptions.

2. **CapabilityProfile placement (step 4.3).** Aggregate per-(problem,
   metric) events into `(mean, variance, p95, n_samples, scaling_slope)`
   per axis. Open: where does the type live, when is it computed, and how
   is it persisted? Candidates:

   - New domain dataclass + free-function aggregator over events. Lazy.
   - New domain dataclass attached to `Trial` (e.g.,
     `Trial.capability_profile: CapabilityProfile | None`), eager at
     finalize.
   - Aggregator lives on the scorer port.

3. **scaling_slope definition (step 4.3, 4.4).** The plan describes the
   deliverable as "trials whose scaling slope distinguishes 'uniformly
   moderate' from 'cheap-then-explodes' configurations" — that's the
   semantics the slope must capture. Candidates:

   - OLS slope of `(difficulty, value)` in linear space.
   - OLS slope of `(difficulty, log(value))` — exponential cliff model.
   - Discrete difference: `value@max_difficulty - value@min_difficulty`.

4. **lifecycle vs. watchdog responsibility (step 4.2 substep).** The
   plan's Phase 4.2 wording — "lifecycle.py only handles telemetry-
   classified outcomes, while watchdogs handle `boundary_violation`" —
   predates ADR 0011, which already executed exactly that split: today
   `lifecycle.classify_outcome` reads the event stream first, and
   watchdogs emit `boundary_violation` events rather than assigning
   `Trial.outcome` directly. The substep is therefore *confirmation-and-
   document*, not refactor. ADR 0012 records this so Phase 4.2's
   acceptance criteria do not double-charge for work ADR 0011 already
   landed.

These questions are coupled — the event shape determines what the
aggregator reads; the aggregator's location determines whether the
profile is persisted or lazy; the slope definition determines what
events must carry. Settling them in one ADR avoids three rounds of
churn.

## Options Considered

### Event shape

**E1. Replace `scored_objective` with `metric_record` events.** One event
per `(problem, metric_name)` pair. Payload: `{problem_id, metric_name,
value, n_samples}`. The `eval` event still carries `exit_code` and
problem-level signals.

- **Pros:** Literal reading of step 4.2; uniform shape; trivially extends
  to Phase 5 subjective scores (one more metric_name) and Phase 6
  replication (n_samples > 1). The CapabilityProfile aggregator becomes a
  `filter(events, phase == "metric_record")` group-by-metric_name.
- **Cons:** Event count per trial grows from `2 * N_problems` to
  `(1 + M_metrics) * N_problems` (5× per problem in v1). Per-trial
  `events.jsonl` grows correspondingly; still O(KB) at v1 scale.

**E2. Keep `scored_objective` AND emit `metric_record`.** Both shapes
land in `events.jsonl`.

- **Pros:** Backward-compatible for consumers reading `scored_objective`
  today.
- **Cons:** Two ways to ask the same question; consumers drift apart;
  redundant disk. We have one consumer today (CapabilityProfile, not yet
  written) and one acceptance test reading `scored_objective` payload
  fields — both updatable in the same commit. No backward-compat debt.

**E3. Extend `scored_objective` payload.** Single event per problem with
`{metric_name: (value, n_samples)}` dict inside.

- **Pros:** Smallest delta; no new event phase.
- **Cons:** Diverges from the plan's literal "one event per pair"
  wording; dict-valued payloads are harder to grep / filter via the
  event-stream primitives the project leans on (see ADR 0011's framing).
  Phase 6's surrogate feature extraction wants per-metric streams anyway.

### CapabilityProfile placement

**P1. Domain dataclass + free-function lazy aggregator.** Type lives in
`domain/types.py` (or `domain/capability_profile.py`). Aggregator is a
free function `capability_profile(trial: Trial) -> CapabilityProfile`,
computed on demand from `trial.events`. Not persisted.

- **Pros:** Hexagonal-clean — domain stays pure, no I/O coupling. The
  event stream is the durable record (ADR 0011 framing); the profile is
  a derived view, like the Pareto frontier already is.
- **Cons:** Recomputed on every access. Negligible cost at v1 scale
  (≤100 trials, ≤10 problems each, ≤5 metrics).

**P2. Eager profile, attached to Trial, persisted in final.json.**
`Trial.capability_profile: CapabilityProfile | None`, populated at
finalize, written to `final.json` alongside (or replacing) `Metrics`.

- **Pros:** Single computation; persisted view; consumers don't re-derive.
- **Cons:** Two SoTs for the same information; if the aggregation formula
  changes (e.g., we switch slope from linear to log-linear), historical
  `final.json` files carry stale numbers. The derive-don't-store
  discipline of ADR 0011 and the preservation-queue note in
  `design-notes.md` argues against this.

**P3. Profile lives on the scorer.** `ScoringPort` grows a third method
`aggregate_profile(trial) -> CapabilityProfile`.

- **Pros:** Co-locates scoring concerns.
- **Cons:** The aggregation is a pure projection over events — no
  scoring decisions enter it. Putting it behind a port adds a substitution
  surface no use case currently needs. Reconsider when a non-default
  aggregation (e.g., Bayesian shrinkage over n_samples) emerges.

### scaling_slope definition

**S1. Linear OLS over `(difficulty, value)` per axis.** For each metric,
fit `value = a + b * difficulty` and report `b`. Slope sign matches the
axis direction: positive slope on cost axes means "grows with difficulty"
(bad), positive slope on quality means "grows with difficulty" (good).

- **Pros:** Simplest closed form; uniform across axes; deterministic;
  one number per axis. The plan's "uniformly moderate vs. cheap-then-
  explodes" semantics: a flat trial has slope ≈ 0; a cliff trial has
  large positive slope on cost axes.
- **Cons:** Doesn't model exponential blow-ups well — a 10× jump from
  difficulty 2→3 fits poorly to a linear line. With only 3 difficulty
  levels in v1, OLS is approximately equivalent to a least-squares fit
  through 3 points; not enough samples to distinguish linear from
  exponential robustly anyway.

**S2. Log-linear OLS — `log(value)` vs. difficulty.** Captures
exponential cliffs cleanly. Slope is `1 / e-folding-difficulty`.

- **Pros:** Honest model of "cheap-then-explodes."
- **Cons:** Undefined on zero values (quality at 0, tokens at 0 for a
  no-op trial); needs an offset / `log1p`. With 3 data points the model
  choice (linear vs. log-linear) is not statistically distinguishable.
  Reconsider at Phase 5+ once n_problems or replication grows.

**S3. Discrete difference.** Single number per axis: `value@D_max −
value@D_min`.

- **Pros:** Intuitive; no fitting machinery.
- **Cons:** Loses middle-difficulty signal entirely; degenerates for
  trials missing the extreme problems (e.g., a boundary-violated trial
  that only ran 001 and 002).

## Decision

The four sub-questions resolve as follows.

**1. Event shape: E1.** `TrialRunner` retires the `scored_objective`
event and emits one `metric_record` event per `(problem, metric_name)`
pair. The `eval` event continues to carry `exit_code` and other
problem-level scalars (not per-metric values). Metric names in v1:
`tokens_consumed`, `cost_dollars`, `validation_pass_rate`,
`quality_score`. Payload:

```json
{"problem_id": "001_binary_search",
 "metric_name": "cost_dollars",
 "value": 0.0123,
 "n_samples": 1}
```

`n_samples = 1` in v1 because trials run each problem once (ADR 0006 is
still open on replication). The field is in the schema now so Phase 5
replication and Phase 6 surrogate weighting can read it without a schema
fork.

**2. CapabilityProfile placement: P1.** A new domain dataclass
`CapabilityProfile` lives in `domain/types.py` (or a dedicated module if
file size warrants). A free function `capability_profile(trial: Trial)
-> CapabilityProfile` in `domain/capability_profile.py` derives the
profile lazily from `trial.events` (filtering on `phase ==
"metric_record"`). The profile is **not** persisted to `final.json`;
`final.json` continues to carry the flat aggregate `Metrics` for
trial-level summary, and the profile is reconstructed from
`events.jsonl` when needed. Consumers that want the profile call the
aggregator; consumers that want a one-line summary read `final.json`.

Shape:

```python
@dataclass(frozen=True)
class MetricSummary:
    mean: float
    variance: float
    p95: float
    n_samples: int
    scaling_slope: float

@dataclass(frozen=True)
class CapabilityProfile:
    per_metric: dict[str, MetricSummary]  # keyed by metric_name
```

With v1's `n_samples = 1` per problem, `variance = 0.0` and `p95 = value`
trivially — they exist in the schema for Phase 5+ replication where they
become non-trivial.

**3. scaling_slope: S1 (linear OLS).** For each metric, fit `value = a +
b * difficulty` across the problems the trial actually ran; report `b`.
With fewer than 2 distinct difficulty levels in a trial,
`scaling_slope = 0.0`. Difficulty is read from `GraduatedProblem.difficulty`
via the per-event `problem_id` lookup against the suite. The slope is
recorded per-axis; sign conventions match the Pareto-domination axes —
cost axes minimized (positive slope = degradation), quality axis
maximized (positive slope = improvement).

Reconsider triggers below capture the log-linear question for later.

**4. lifecycle vs. watchdog: confirm-and-document.** ADR 0011 already
established that `lifecycle.classify_outcome` reads the event stream
first and watchdogs emit `boundary_violation` events. Phase 4.2's
lifecycle-substep is therefore documentation — no code change required
beyond confirming via test that the invariant holds when 002 and 003
problems are present. The Phase 4.2 acceptance criteria mark this
substep complete via a one-line cross-reference to ADR 0011.

## Reconsider Triggers

- **Log-linear scaling becomes load-bearing.** If 4-5 difficulty levels
  land in Phase 5+ and the surrogate's feature shape benefits from
  exponential-cliff discrimination, switch S1 → S2. The aggregator
  signature stays; only the slope computation changes. Historical
  `events.jsonl` files don't need rewriting because the profile is
  re-derived on read.
- **Profile shape needs persistence.** If a consumer (a `pi-eval show`
  CLI, a notebook view) computes the profile so often that re-derivation
  cost matters, promote it from "lazy derived view" to "persisted in
  `final.json`" via an additive field — but keep the event stream as
  SoT, so the persisted profile is a cache, not a record.
- **Per-role attribution lands** (ADR 0005 reconsider trigger). When the
  surrogate needs per-role cost attribution, `metric_record` payloads
  grow a `role` field and the aggregator groups by `(metric_name,
  role)`. This is additive — existing metric_record events without a
  `role` field aggregate as today.
- **n_samples > 1 changes the variance / p95 calculation.** Once
  replication lands (ADR 0006), variance and p95 become non-trivial.
  Today they're degenerate-but-honest (variance = 0 because a single
  sample has no spread); when n_samples > 1 the aggregator's existing
  formulas just start producing real numbers without a schema change.

## Consequences

- `TrialRunner.run_trial` retires the `scored_objective` event and emits
  `metric_record` events instead. The `eval` event is unchanged.
- `SyntheticSuiteScorer.score_objective` continues to return `Metrics`
  (per-problem); the TrialRunner translates each `Metrics` into N
  `metric_record` events. Scorer port shape unchanged in v1; that
  preserves Phase 1-3 adapter tests.
- A new `domain/capability_profile.py` module defines `MetricSummary`,
  `CapabilityProfile`, and `capability_profile(trial)`. `Trial` itself
  is not modified — the profile is a derived view.
- `domain/pareto.py` Phase 4.4 extension reads from
  `CapabilityProfile.per_metric` rather than `Trial.final_metrics`,
  using `(mean_tokens, mean_dollars, scaling_slope_on_cost,
  mean_quality)` as the four Pareto axes. The exact slope axis for the
  4D frontier — slope of tokens, or slope of dollars, or
  max-of-both — is fixed at implementation time per Phase 4.4 acceptance
  test results. (My current intent: slope of cost_dollars, because the
  dollar cliff is the operator-facing harm; tokens-slope is recorded in
  the profile for diagnostics.)
- `final.json` schema is unchanged in v1. `Metrics` still carries the
  flat aggregate; the capability profile is re-derivable from
  `events.jsonl`.
- The Phase 4.2 plan-step substep (lifecycle vs. watchdog) is
  documentation-only; no code change required.
- Tests touched: `test_trial_runner.py` (new metric_record event
  assertions; retire `scored_objective` assertions), `test_pareto.py`
  (4D dominance), new `test_capability_profile.py` (aggregation,
  scaling_slope edge cases).
- The `Open spikes` table in `docs/implementation-plan.md` gains an
  entry for the in-flight 0012 spike and loses it when this ADR flips to
  Accepted. The previously planned 0012 ("boundary-violated trials
  visibility") moves to ADR number 0013 — numbering is by open-date per
  `docs/adrs/README.md`.
