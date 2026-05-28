# Phase 4 Acceptance Test — Capability Profile and Scaling Slope

*Point-in-time snapshot, 2026-05-28. Like the other phase demos
(`phase{1,2,3}_demo.md`), this file documents the test as it stood when
Phase 4 landed; it is **not** a living spec — see ADR 0012, the
implementation plan, and the test source for the up-to-date contract.*

## Overview

`tests/test_acceptance_phase4.py` validates the Phase 4 deliverable from
`docs/implementation-plan.md`:

> Trials over a multi-difficulty suite produce capability profiles whose
> scaling slope distinguishes "uniformly moderate" from "cheap-then-
> explodes" configurations.

It's a deterministic stub-based test rather than an `acceptance_full`
real-Pi exercise. The Phase 4 contract is about the
**events → profile → frontier** pipeline, not provider behavior; we
pre-program the per-problem cost via a stub scorer so the slope axis can
be exercised without relying on a particular model's actual cost curve.
The real-Pi acceptance for slope-discrimination behavior is best
validated as part of Phase 6 (which actually consumes the slope axis in
the surrogate), so we don't open an `acceptance_full` variant for
Phase 4.

The test exercises the **real** `GraduatedProblemSetAdapter` against the
real `graduated_problems/` directory (001/002/003), so suite-loading and
the difficulty-ordering convention are honest. Only the harness and
scorer are stubbed.

## Feature 1 — `CapabilityProfile` aggregates per-(problem, metric) events

Per **ADR 0012**, each problem emits one `eval` event (carrying
`problem_id`, `difficulty`, `exit_code`) followed by one `metric_record`
event per axis. The `capability_profile(trial)` free function in
`pi_evaluator/domain/capability_profile.py` joins them by `problem_id`
and computes per-axis `(mean, variance, p95, n_samples, scaling_slope)`.

```python
trial = _run_trial(tmp_path / "shape", "t-shape", [3.0, 3.0, 3.0])
phases = [e.phase for e in trial.events]
per_problem = ["eval"] + ["metric_record"] * 4
assert phases == ["configured"] + per_problem * 3 + ["finalized"]
```

With three problems in the suite and four metric axes (tokens, dollars,
pass-rate, quality), the per-trial event stream grows to 17 events:
`configured`, `(eval + metric_record × 4) × 3`, `finalized`.

## Feature 2 — Scaling slope on `cost_dollars` distinguishes flat from cliffy

The test constructs two trials over the same 3-problem suite:

- `flat`: per-problem `cost_dollars = [3.0, 3.0, 3.0]`. Mean = 3.0.
  Slope = 0.0 (no growth with difficulty).
- `cliffy`: per-problem `cost_dollars = [1.0, 3.0, 5.0]`. Mean = 3.0.
  Slope > 0 (linear cost growth with difficulty).

Float-exact inputs were chosen deliberately: both lists sum to 9.0 and
average to 3.0 bit-for-bit under IEEE-754, so the means tie exactly and
any 4D Pareto separation must be driven by `scaling_slope`. (The earlier
draft with `[0.1, 0.1, 0.1]` vs. `[0.01, 0.10, 0.19]` failed in
`test_pareto.py` because `0.1+0.1+0.1 != 0.01+0.10+0.19` in float; the
lesson is captured here.)

```python
flat = _run_trial(tmp_path / "flat", "t-flat", [3.0, 3.0, 3.0])
cliffy = _run_trial(tmp_path / "cliffy", "t-cliffy", [1.0, 3.0, 5.0])

flat_profile = capability_profile(flat)
cliffy_profile = capability_profile(cliffy)

assert flat_profile.per_metric["cost_dollars"].scaling_slope == pytest.approx(0.0)
assert cliffy_profile.per_metric["cost_dollars"].scaling_slope > 0.0
assert flat_profile.per_metric["cost_dollars"].mean == pytest.approx(3.0)
assert cliffy_profile.per_metric["cost_dollars"].mean == pytest.approx(3.0)
```

## Feature 3 — 4D Pareto frontier excludes the cliffy trial

With means tied across all three flat-axes (`mean_tokens`,
`mean_dollars`, `mean_quality`) and the slope axis breaking the tie, the
frontier excludes `cliffy`. This is the load-bearing assertion: it shows
that the Phase 4 slope axis actually changes the Pareto outcome, not
just the profile reporting.

```python
frontier = pareto_frontier([flat, cliffy])
assert {t.trial_id for t in frontier} == {"t-flat"}
```

Per **ADR 0012**'s decision: only the `cost_dollars` slope is a Pareto
axis in v1; the `tokens_consumed` slope is recorded for diagnostics but
not used in dominance. A third test asserts the tokens-slope diagnostic
is present without claiming it affects the frontier.

## Why no real-Pi acceptance for Phase 4?

Two related reasons:

1. **The slope axis has no consumer that needs cost-curve fidelity in
   Phase 4.** Phase 6's surrogate will be the first consumer that
   actually fits the slope; that's where real-Pi acceptance of
   slope-driven behavior earns its keep.

2. **Real-Pi cost-curve reproducibility is the wrong gate for the
   v1-Phase-4 contract.** Per ADR 0006, provider non-determinism makes
   real cost curves noisy at low replication; we'd need the
   replication/HetGP machinery from Phase 6 to assert anything specific
   about *measured* slope values.

If a future need surfaces — e.g., regression suspicion that a real Pi
run no longer emits per-problem cost records — open an
`acceptance_full` variant then; ADR 0010's tiering supports it.

## Running

From the `python/` directory:

```shell
mise run test  # includes Phase 4 acceptance test (no real Pi required)
```

Or just the Phase 4 test:

```shell
uv run pytest tests/test_acceptance_phase4.py -v
```
