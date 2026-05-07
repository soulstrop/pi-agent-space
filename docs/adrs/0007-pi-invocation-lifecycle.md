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

Four coupled questions:

1. **Timeout policy.** Hard wall-clock cap per trial, soft cost-based cap (terminate when accumulated tokens or dollars exceed a threshold — interacts with ADR 0005), or both?

2. **Signal handling.** When aborting a hung Pi, send `SIGTERM` → grace period → `SIGKILL`? What grace period? Does Pi handle `SIGTERM` cleanly today (flush state, close session) or just die mid-stream?

3. **Partial-trial recording.** If Pi is killed, is the trial recorded as `failed` (no metrics), `partial` (with whatever telemetry made it through), or `succeeded-with-asterisk` (validated as the workspace state regardless of how the agent got there)? Phase 5's partial-scoring policy is the natural cousin but covers the orthogonal subjective-not-arrived case.

4. **Retry policy.** Are network errors retryable? At adapter level (re-invoke Pi, possibly re-using the materialized workspace) or driver level (re-propose the trial, fresh workspace, count against budget)? Auto-retry interacts with ADR 0005's cost cap and ADR 0006's reproducibility model.

## Options Considered

*To be developed during the spike. Initial sketches:*

### 1. Wall-clock timeout only

Subprocess gets a fixed wall-clock cap (e.g., 10 minutes). On timeout, `SIGTERM` → 5s grace → `SIGKILL`. Trial recorded as partial — keep whatever `RawTelemetry` was parseable, run validation, mark with a `timeout=True` flag.

* **Pros:** simple; provider-agnostic; predictable.
* **Cons:** doesn't distinguish "expensive but productive" from "hung" — a slow but useful trial gets killed at the same threshold as an infinite loop.

### 2. Cost-based abort

Poll Pi's accumulated token / dollar cost (extracted from streaming events); abort when it exceeds the per-trial cap from ADR 0005. Pure cost-based — no wall-clock timeout.

* **Pros:** real-budget protection; productive trials with low cost run as long as they need; lazy trials don't burn budget.
* **Cons:** requires streaming-aware cost tracking (current adapter is post-hoc); cost-only doesn't catch hung-without-token-spend cases (e.g., Pi waiting on a stuck bash).

### 3. No timeout, no abort

Accept that bad trials take their time; ops responsibility to kill from outside. Optimizer driver can track elapsed time externally.

* **Pros:** simplest in code.
* **Cons:** unattended overnight runs are unsafe; one hung trial blocks the whole optimization.

### 4. Hybrid: wall-clock backstop + cost cap

Hard wall-clock cap as a backstop (e.g., 30 minutes — only fires for genuine hangs); cost cap from ADR 0005 as the primary economic protection. Plus a retry policy for classified network errors (e.g., 1 retry on 5xx after 30s).

* **Pros:** covers all five failure modes; matches the way humans actually monitor ops.
* **Cons:** more configuration surface; cost-cap streaming logic adds complexity.

## Decision

TBD — pending spike.

## Reconsider Triggers

TBD — will be filled in alongside the decision.

## Consequences

TBD — will be filled in alongside the decision.
