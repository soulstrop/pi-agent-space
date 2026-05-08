# Title: 0007 - Pi Invocation Lifecycle

**Status:** Accepted

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

**Axis 1 — Classification: A2, source-of-kill-based, with the user-supplied simplification that timeouts count as boundary violations.**

The entity that initiated the kill records the classification:

- **Boundary violation** = the watchdog or driver decided to kill, for a deterministic reason that names a budget the trial blew past. Three concrete sub-reasons land in v1: per-trial cost cap (ADR 0005), per-run cost cap (ADR 0005), wall-clock timeout. All three are *boundaries*; none is ambiguous; none is retried.
- **Error** = anything else Pi self-died on (non-zero exit not initiated by the watchdog, segfault, malformed event stream that breaks parsing). Errors are operationally suspicious — getting "signal" from them involves too much guessing.
- **Operator-initiated kill** (Ctrl-C, external SIGTERM by a human or sysadmin) classifies as **error_escalated** per axis 3 — operators are chaotic, but they take responsibility, so their interventions land in the same human-attention queue as persistent errors.

**Axis 2 — Retry: B1 with bounded budget; persistent errors preserve and queue, do not auto-escalate to the driver as new proposals.**

The adapter retries a trial that hit an *error* (not a boundary violation) up to **N = 2 times** by default, with backoff (exact schedule is design-note territory). The retry runs against the **same materialized workspace** — preserving any state Pi started building before the error. After N retries fail, the trial is **preserved**: its workspace, partial telemetry, exit codes, and stderr are kept on disk, the trial is tagged `error_escalated`, and the optimizer driver moves on to its next proposal. The driver **does not** auto-re-propose persistent errors as fresh trials; that decision belongs to the human-in-the-loop, who reviews the queue asynchronously and classifies (e.g., "this was network down — ignore", "this was actually a boundary violation — count as cost cliff", "this is a real bug — pause runs until fixed").

In addition, the driver implements a **circuit breaker** with two trip conditions, whichever fires first:

- **Consecutive errored trials** exceeding a threshold (default ~5).
- **Wall-clock time without a completed trial** exceeding a threshold T (default ~30 minutes).

When the circuit trips, the driver halts the optimization run gracefully (no more proposals dispatched; the in-flight trial is allowed to complete or hit its own boundary), surfacing the situation to the operator. This catches scenarios like a sustained network outage where every trial errors quickly enough that consecutive-count alone might be slow to recognize. Both thresholds are operator-configurable; the defaults are implementation-time choices that land in `docs/design-notes.md`.

**Axis 3 — Failed-trial metrics: C1, plus new event phases that carry the lifecycle outcome.**

`Metrics` shape stays narrow — consistent with the ADR 0005 preference for keeping the optimization-signal layer clean and putting metadata in telemetry. For boundary-violated trials: `quality_score = 0`, `validation_pass_rate = 0`, `tokens_consumed` and `cost_dollars` carry whatever was spent at abort (real cost — not zero). The lifecycle classification rides in the trial event stream:

- New event phases land in `events.jsonl`: `error_retry` (each adapter-level retry attempt), `error_escalated` (the trial is being preserved and queued for human review), `boundary_violation` (the watchdog/driver killed the trial for a named boundary). These are emitted alongside the existing phase progression — they don't replace `finalized`. Every trial still finalizes.
- The `finalized` event payload gains an `outcome: "completed" | "boundary_violation" | "error_escalated"` field. Surrogate consumers that don't care about lifecycle ignore it; human-facing tools and the human-classification queue use it as the primary filter.

The HetGP from ADR 0006 sees `boundary_violation` trials as data points in feature space — they teach the surrogate where the cost cliff lives. The HetGP does **not** see `error_escalated` trials; those sit in the human-classification queue, and only enter the optimization history if and when a human classifies them (typically as boundary violations after the fact). Errors are deliberately not optimization signal until a human disambiguates.

## Reconsider Triggers

- **Pi gains built-in retry or cost-cap mechanisms** in a future release, superseding adapter-side enforcement.
- **The async human-classification queue accumulates faster than humans can clear it** — operationally signals the need for an auto-classification heuristic (e.g., "errors that look like 5xx + match a known retry-on-this regex are auto-classified as transient and discarded").
- **Persistent errors cluster around specific package configs** — a config consistently errors and a human consistently re-classifies as boundary violation. The classification rule itself needs revision to recognize the pattern.
- **Circuit breaker fires too often or too rarely.** False positives cost optimization time; false negatives waste budget on dead networks. The thresholds may need to become adaptive.
- **Workspace-on-retry semantics cause bugs** — e.g., Pi's tools turn out not to be idempotent and a second pass corrupts state. Forces a switch to fresh-workspace-per-retry, paying the materialization cost.
- **Operator kills become frequent** in practice (e.g., dev workflow involves a lot of Ctrl-C). The operator path may need a less-loaded category than `error_escalated`.

## Consequences

- The adapter (`CliSubprocessAdapter` and successors) gains: retry budget configuration (default `2`), backoff schedule, error-classification logic (watchdog-killed → boundary; everything else → error). The watchdog itself is implemented as part of the adapter or as a sibling helper — exact placement is implementation detail.
- The optimizer driver gains: circuit-breaker policy with two thresholds (max consecutive errored trials, max wall-clock without a completed trial), preservation hook for `error_escalated` trials.
- Three new trial event phases (`error_retry`, `error_escalated`, `boundary_violation`) join the existing phase set (`configured`, `eval`, `scored_objective`, `scored_subjective`, `finalized`). The `finalized` event payload gains an `outcome` field; absent on existing trials it defaults to `"completed"` for backward compatibility.
- `Metrics` shape is unchanged. All lifecycle status is event-stream-only.
- Persistence layer adds a notion of "preserved trial" — concretely, an `error_escalated` trial's directory contains its full `events.jsonl`, the `final.json` with `outcome: "error_escalated"`, and a copy of the materialized workspace (or a reference thereof). Implementation detail (sibling directory? status flag in `final.json`? both?) lands in `docs/design-notes.md`.
- The HetGP from ADR 0006 sees `boundary_violation` trials but not `error_escalated` trials. The human-in-the-loop's classification of escalated trials may add boundary-violation data points after the fact.
- Default values (N retries = 2; circuit-breaker consecutive errors = ~5; circuit-breaker time-without-success T = ~30 minutes; retry backoff schedule) are implementation-time choices documented in `docs/design-notes.md` when chosen — not committed by this ADR.
- Implementation-mechanism details (`SIGTERM` grace period, partial-event-stream recovery, workspace cleanup on abort, exact preservation layout) defer to design-notes per the established sub-decision-deferral pattern.
