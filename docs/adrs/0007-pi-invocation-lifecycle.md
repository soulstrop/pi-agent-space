# Title: 0007 - Pi Invocation Lifecycle

**Status:** Proposed

*Spike in progress; decision target Phase 3.4.*

## Context

The Phase 2 `CliSubprocessAdapter` invokes Pi with a plain `subprocess.run(...)` — no timeout, no abort hooks, no retry policy, no signal-handling beyond what Python's defaults give. For interactive single-trial development this is fine; for the unattended multi-trial loops Phase 3+ introduces, it isn't. Specific failure modes that need a deliberate policy:

1. **Hung runs.** Pi waiting on a hung tool call (`bash` invocation with no stdin handler), an infinite-loop generation, or a stuck network connection to the LLM API.
2. **Network errors.** Provider rate limits, transient 5xx, DNS failures, timeouts on the LLM-API side.
3. **Partial JSON output.** Pi crashes mid-stream, leaving an incomplete events stream on stdout. Adapter's `_parse_event_stream` skips unparseable lines but a half-emitted JSON object sits between the last good line and the crash.
4. **Half-finished workspaces.** Aborting Pi mid-tool-call may leave the materialized workspace partly mutated. Validation runs against it anyway (per the design-note "Validation always runs"), but the recorded state may be misleading.
5. **Long-running but productive.** A trial legitimately taking 10+ minutes (large problem, deep tool chain) is qualitatively different from "hung" — distinguishing them matters.

The five failure modes resolve along **two qualitatively different axes**, with a third question riding on the second:

> Timeouts (and other non-clean exits) indicate either an **error** or a **boundary-condition violation**. Errors require debugging and possibly retry. Boundary violations are *failures* — strong negative signal. The two paths look different all the way down.

Three sub-questions follow:

1. **Error vs. boundary classification.** What signals classify a non-clean Pi exit as a retry-eligible *error* versus a hard *boundary violation*? Clean cases: a transient HTTP 5xx from the LLM provider → error; the per-trial dollar cap from ADR 0005 hit → boundary violation. Ambiguous cases: a generic wall-clock timeout — was Pi hung waiting on a stuck network call (error?) or genuinely productive but slow past the budget (boundary?). The classification rules drive everything downstream.

2. **Retry policy under the error path.** When Pi exits with an error-class signal, what is the retry budget per trial? Backoff schedule (linear, exponential)? Workspace handling (re-invoke Pi against the same materialized workspace, or re-materialize fresh)? When does a persistent failure escalate to the human-in-the-loop instead of consuming more retries? Retry interacts with ADR 0005's cost cap (retries cost real money) and ADR 0006's reproducibility model (retried trials are not independent samples).

3. **Failed-trial metrics representation** (cross-referenced from ADR 0006). When a trial hits a boundary violation and is killed mid-flight, what does its `Metrics` record carry? The framing committed to in ADR 0006 is that *failures are signal, not loss* — the heteroscedastic GP sees them in feature space and learns the cost / boundary cliff. Spelling out a strawman that we'll either adopt or argue with: `quality_score = 0` (the agent didn't deliver), `validation_pass_rate = 0` (no validation passed, or validation didn't run), `tokens_consumed` and `cost_dollars` set to whatever was actually spent at the moment of abort (not zero — the run cost real budget). The decision needs to confirm or refine this and pin which tag distinguishes "completed with bad metrics" from "killed at the cap."

Implementation-detail mechanisms (signal handling — `SIGTERM` grace period, `SIGKILL` fallback; partial-event-stream parsing on crash; workspace cleanup policy) are downstream of these three policy questions and stay design-note territory once the policy lands.

## Options Considered

*To be developed during the spike. Initial sketches mapped to the three sub-questions above:*

### Classification axis: how to assign error vs. boundary

**A1. Exit-code-based.** Distinguish by Pi's exit code (and known classifiers like Python's `subprocess.TimeoutExpired`). Network errors surface in Pi's stderr or as specific exit codes; cap-hits surface as a deliberate kill-by-watchdog with a known signal.
* **Pros:** mechanically simple; observable.
* **Cons:** Pi may not differentiate cleanly today — generic non-zero exits may need to default one way or the other.

**A2. Source-of-kill-based.** The killer always knows why: a watchdog enforcing the cost cap from ADR 0005 *causes* the boundary violation; an external SIGTERM (from the user, the OS) is treated as a boundary violation; everything else (Pi self-terminates, returns a non-zero exit) is an error candidate.
* **Pros:** authoritative — the entity that initiated the kill records the classification.
* **Cons:** requires the watchdog/driver to be the canonical classifier rather than inferring from artifacts.

### Retry-policy axis (under the error path)

**B1. Bounded retries with exponential backoff at the adapter layer.** N attempts (default 2), backoff 30s/60s; same materialized workspace; if all attempts fail, escalate the trial as an error to the driver.
* **Pros:** standard pattern; no driver re-proposing.
* **Cons:** retries against a possibly-mutated workspace could compound errors.

**B2. Re-propose-at-driver for persistent errors.** Adapter does no retries; on error exit, the driver re-proposes the same `(package, problem)` against a fresh materialized workspace, counted against the trial budget.
* **Pros:** clean state; cost-aware via the driver's budget.
* **Cons:** higher cost (re-materialize, re-run); the surrogate sees retried runs as "new" samples that are not really independent.

**B3. No retries; everything escalates immediately.** Errors are surfaced to the human-in-the-loop without auto-retry.
* **Pros:** simplest; honest about non-determinism.
* **Cons:** inappropriate for unattended overnight runs.

### Failed-trial-metrics axis

**C1. Strawman: zero quality, real cost.** As described above — `quality_score = 0`, `validation_pass_rate = 0`, `tokens_consumed` / `cost_dollars` carry whatever was spent at abort. Boundary violations get a `boundary_violation: true` tag in the trial event payload so post-hoc analysis can distinguish "killed" from "delivered badly."
* **Pros:** keeps `Metrics` shape unchanged; HetGP from ADR 0006 sees data points without special-casing.
* **Cons:** silently conflates "tried but produced 0 quality output" with "killed before validation could run" unless the tag is consulted.

**C2. Failure as a separate type, not a `Metrics` record.** Boundary violations record a `FailureRecord(reason, accrued_cost)` in `final.json` instead of `Metrics`. Surrogate consumers special-case the failure type.
* **Pros:** type system reflects the qualitative difference; no zero-value masquerade.
* **Cons:** every consumer (scorer, surrogate, persistence loader, Pareto frontier computation) needs failure-aware code paths.

**C3. Hybrid: `Metrics` always, with a `status` enum.** Add `status: "completed" | "boundary_violation" | "error_escalated"` to `Metrics`. Status of `completed` carries the usual numbers; the others carry zeros and the spent-cost values plus the status tag.
* **Pros:** explicit; backward-compatible if `status` defaults to `"completed"` on existing trials.
* **Cons:** `Metrics` accumulates lifecycle metadata that arguably belongs in the trial event stream rather than the metrics record.

## Decision

TBD — pending spike.

## Reconsider Triggers

TBD — will be filled in alongside the decision.

## Consequences

TBD — will be filled in alongside the decision.
