# Title: 0011 - Outcome Classifier as Single Source of Truth

**Status:** Accepted

## Context

The trial pipeline (`trial_runner.py:run_trial`) resolves the `Trial.outcome` field via two disjoint paths:

- **Watchdog override.** When the cost-cap watchdog trips, it emits a `boundary_violation` event into `events.jsonl` *and* directly assigns `outcome = "boundary_violation"` at finalize time, bypassing the classifier entirely.
- **Classifier path.** Otherwise, `_classify_outcome(per_problem_telemetry)` runs `lifecycle.is_model_error` over the per-problem telemetry: a non-zero exit code or an assistant `message_end` with `stopReason == "error"` yields `error_escalated`, else `completed`.

This worked for v1 with a single boundary trigger (cost cap), but Phase 3.4's still-owed work and Phase 4.2's new lifecycle phases break it:

- **Subprocess timeout** (issue `pi-agent-space-y55`). ADR 0007 A2 commits to timeouts being source-of-kill-classified as `boundary_violation`. But a `TimeoutExpired` produces `exit_code != 0`, which `lifecycle.is_model_error` treats as `error_escalated`. Without an explicit watchdog-override path for timeout, the outcome is misattributed.
- **Sandbox-kill** (future, ADR 0009). Same trap: bwrap resource-limit kills produce non-zero exit and would route to `error_escalated` despite being infrastructure boundary trips, not model errors.
- **Phase 4.2** introduces `error_retry` and `error_escalated` event phases (plan L169). If those are emitted at telemetry-classification time but the classifier still reads from raw telemetry at finalize time, the events become decoration rather than authoritative — two ways to ask "is this an error?", neither aware of the other.

The unifying observation: `events.jsonl` is already the per-trial single authoritative log. Watchdogs emit into it (cost-cap does today). Telemetry predicates *could* emit into it. The disagreement is purely about how `outcome` is *decided*, not how events are *recorded*. Today the decision rule reads two separate inputs (events vs. telemetry) with no precedence rule between them; that's the structural problem.

The Phase 4.2 "hard precondition" framing from the plan asked: who owns the final outcome — an inline watchdog override, or a single event-stream-driven classifier reading the trial's emitted phases?

## Options Considered

**A. Event-stream-first classifier (single SoT).** The classifier becomes the sole assigner of `Trial.outcome`. It reads `events.jsonl` first, with the rule: any `boundary_violation` event → `boundary_violation`; else apply the telemetry predicate (`lifecycle.is_model_error` over `per_problem_telemetry`). Watchdogs still own emitting their `boundary_violation` events with the cause in the payload (`per_trial_cost_cap`, future `subprocess_timeout`, future `sandbox_kill`), but they stop directly writing the outcome field. The classifier becomes a one-line function of the trial event stream and per-problem telemetry; there is only ever one place to look when asking "why did this trial get this outcome?"
- **Pros:** Eliminates the watchdog-vs-classifier ambiguity that spike 0008 was opened to call out. Naturally accommodates future kill sources (subprocess timeout, bwrap sandbox-kill) — they just emit the right event; classifier needs no change. Aligns with `lifecycle.py`'s existing scoping rule ("watchdog-classified outcomes are owned by their killer") — the killer still emits; the classifier queries. The event stream remains the durable record, and `outcome` becomes a derived view of it.
- **Cons:** A new ordering invariant: the classifier must be called *after* every watchdog has had its chance to emit. Today this is trivial (the cost-cap watchdog and the finalize step share one function), but future watchdogs (subprocess timeout running concurrently with the agent subprocess) will need to settle their emissions before finalize. A one-line concern, but it must be explicit.

**B. Status quo — watchdog override + telemetry classifier.** Keep the current two-path resolution. Each new kill source adds its own `if <killed>: outcome = "boundary_violation"` block alongside the existing cost-cap one.
- **Pros:** Mechanically simple; no rearchitecture. Each watchdog is self-contained.
- **Cons:** Misattribution risk grows with every new kill source — the precise problem this ADR was opened to prevent. Three or more disjoint override paths is the classic "every author of a watchdog has to remember to write the right line." `lifecycle.is_model_error`'s `exit_code != 0` rule already misclassifies anything that exits non-zero unless explicitly intercepted upstream; that's a footgun that grows worse, not better.

**C. Pure event-stream classifier (no telemetry fallback).** Go further than A: lifecycle predicates emit `error_escalated` events at telemetry-classification time, and the classifier becomes a one-line lookup over `events.jsonl` with no per-telemetry inspection at finalize. `lifecycle.is_model_error` becomes an *emission-time* predicate; the classifier becomes pure projection over the event stream.
- **Pros:** Cleanest possible separation: predicates produce events; classifier consumes events; outcome is mechanically derived. Symmetric across all kill sources (watchdog or telemetry-classified).
- **Cons:** Requires deciding *when* during the trial to emit `error_escalated` — at what point during the per-problem loop does telemetry get classified? Today this happens at finalize, accumulated across all problems. Moving emission to mid-trial requires committing to per-problem classification semantics, which is a separable decision. Phase 4.2 brings the `error_retry` / `error_escalated` event phases that would make this natural, but it isn't natural *yet*. Premature here; right answer later.

## Decision

**Option A.** The classifier becomes the single source of truth for `Trial.outcome`, with the routing:

```python
def classify_outcome(events: list[TrialEvent],
                     per_problem_telemetry: list[RawTelemetry]) -> Outcome:
    if any(e.phase == "boundary_violation" for e in events):
        return "boundary_violation"
    if any(lifecycle.is_model_error(t) for t in per_problem_telemetry):
        return "error_escalated"
    return "completed"
```

- The cost-cap watchdog (today) and the future subprocess-timeout / sandbox-kill watchdogs emit a `boundary_violation` event with their cause in the payload, and stop directly assigning `Trial.outcome`. Cause-in-payload (`reason: "per_trial_cost_cap" | "subprocess_timeout" | "sandbox_kill"`) is what distinguishes kill sources; the outcome enum stays at three values.
- `TrialRunner.run_trial` invokes the classifier exactly once, *after* the per-problem loop (and any in-loop watchdog emissions) has settled, and assigns the result to `Trial.outcome`. The `finalized` event payload's `outcome` field is the classifier's return value.
- The ordering invariant — "classifier runs after every watchdog has had its chance to emit" — is honored today by the sequential structure of `run_trial`. Future concurrent watchdogs (subprocess-timeout running parallel to the agent subprocess) must join/settle before the classifier is invoked.
- `lifecycle.py`'s scoping docstring is updated to reflect the new contract: `lifecycle.is_model_error` is the telemetry predicate the classifier consults; `boundary_violation` ownership stays with the killer (in the form of *event emission*, not outcome assignment).

## Reconsider Triggers

- **`error_retry` / `error_escalated` event phases land (Phase 4.2).** Once those event phases are part of the per-trial stream, Option C becomes viable: `lifecycle.is_model_error` moves to emission-time, the classifier becomes pure projection over events, and the per-problem telemetry parameter drops off. Open a successor ADR at that point — keep this one Accepted as the intermediate state.
- **Concurrent watchdog emission complicates the ordering invariant.** If a future watchdog runs in a separate thread/task and finalize gets called before its `boundary_violation` event lands in `events.jsonl`, the classifier returns the wrong answer. The fix is a settlement primitive (join the watchdog before finalize), not abandoning Option A — but it's an explicit reconsider trigger because it changes the test surface.
- **Cause-in-payload outgrows the enum.** If `Outcome` itself needs to differentiate kill sources (e.g., the surrogate needs to weight cost-cap-cliffs and timeout-cliffs differently), the three-value enum needs to grow. That's an ADR 0007 amendment, not an ADR 0011 amendment, but the work would surface here first.

## Consequences

- `TrialRunner.run_trial` is restructured: the watchdog `outcome = "boundary_violation"` override at line 164 (today) goes away; finalize invokes the classifier once over `trial.events` and `per_problem_telemetry`.
- The classifier moves out of `trial_runner._classify_outcome` (per-telemetry only) into a dedicated function — likely `lifecycle.classify_outcome(events, per_problem_telemetry)` so the predicate and the classifier live together, or `domain/outcome.py` if `lifecycle.py` is to stay strictly emission-side. Decided at implementation time.
- Issue `pi-agent-space-1vc` (subprocess-timeout → `boundary_violation` trigger) becomes mechanical: the timeout watchdog emits a `boundary_violation` event with `reason: "subprocess_timeout"`; no classifier change needed beyond what this ADR specifies.
- Spike 0008 closes. The row is removed from `docs/implementation-plan.md`'s Open spikes table. Phase 4.2's "Hard precondition: spike 0008 must close before 4.2 begins" rewrites to "Phase-entry condition (ADR 0011): the outcome classifier reads the per-trial event stream as its primary input; watchdogs emit `boundary_violation` events rather than assigning outcomes directly."
- Future bwrap sandbox-kill work (ADR 0009 reconsider trigger) inherits the routing — the sandbox-kill is just another watchdog emitting a `boundary_violation` event with `reason: "sandbox_kill"`.
- The event-stream-as-SoT framing strengthens the "`finalized` is last" invariant: every input to `outcome` is observable in `events.jsonl` before `finalized` is written.
