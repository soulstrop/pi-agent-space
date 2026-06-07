# Title: 0022 - Observability Suite

**Status:** Accepted

*Accepted 2026-06-07. Closes spike S007 and issue `pi-agent-space-5eb`.
Extends [ADR 0015](0015-structured-logging-depth.md) (logging) to the two
remaining observability pillars: operational metrics and phase tracing.*

## Context

ADR 0015 delivered the **logging** pillar (structured JSON, `contextvars`
correlation, `QueueListener` isolation) and is done (`pi-agent-space-ent`). The
Phase-7 observability workstream (spike S007) asks what the *other two* pillars —
**metrics** and **tracing** — commit to for v1.

The operational signal today is thin. The run-event stream
(`run_events.jsonl`, ADR 0013) records only `run_started` /
`per_run_cost_cap_warning` / `run_halted`; `OptimizerResult` is in-memory and
never persisted as a summary; and there is no per-phase timing anywhere. For an
unattended overnight run (ADR 0007) an operator cannot answer "how many trials
completed vs. boundary-violated, what did it cost, and where did the time go?"
from the artifacts alone.

The deployment scenario is unchanged from ADR 0015/0020: a **single operator
running synthetic-suite R&D** on their own machine. That sizes the answer — the
same way it sized ADR 0015's "stdlib-only, stdout + `run.log`, no OpenTelemetry"
posture.

## Decision

### D1 — Three pillars, one house posture: stdlib-only, OTel deferred

Metrics and tracing adopt ADR 0015's posture verbatim: **no new dependency**,
in-process, output via the existing structured-log stream plus a run-directory
artifact. **OpenTelemetry is not taken as a v1 dependency**; it is deferred
behind the same enterprise-deployment trigger as ADR 0015's OTel *transport*
(MD2) and field-allowlist redaction (MD6-B). When logs/metrics leave the local
host, OTel becomes load-bearing — and lands as an *adapter*, not a rewrite (D3).

### D2 — Metrics are a derived `run_summary.json` + a structured log event

Operational metrics for a run are aggregated into a `RunSummary` (domain type):
outcome counts (`trials_completed` / `trials_boundary_violation` /
`trials_error_escalated` / `trials_total`), `total_cost_dollars`,
`wallclock_seconds`, `trials_per_minute`, and per-phase `spans`. At run end the
summary is **persisted as `run_summary.json`** in the run directory (ADR 0013
layout) and **emitted as a structured `run_summary` log event** (so it is
visible in the same JSON stream as everything else, MD4-A snake_case).

`run_summary.json` is deliberately distinct from `final.json`: `final.json` is
per-trial **capability** data (the optimizer's measurement); `run_summary.json`
is **operational** data about the run itself. Conflating them would muddy the
schema-governance surface (ADR 0019).

### D3 — A thin `ObservabilityPort` seam, in-process default

Metrics/tracing flow through a dedicated **`ObservabilityPort`** (a thin sink:
`increment` / `record` / `span` / `finish_run`) — *not* baked into the driver
and *not* folded into `PersistencePort`. This keeps the seam pluggable: the v1
`InProcessObservability` adapter aggregates in memory and writes the artifact +
log event; a future OTel adapter forwards the same three verbs to the OTel SDK
with no change to call sites. `NullObservability` is the **no-op default**, so
observability is opt-in (mirroring ADR 0015's `configure_logging`) and an
unconfigured run pays nothing and behaves exactly as before.

Why a port rather than extending `PersistencePort`: emitting live operational
signal (counters, spans, push to a collector) is a different responsibility from
durably storing trial artifacts. Tying metrics to `PersistencePort` would force
every future transport (OTel push) through a storage interface it does not fit.
The one concession to storage is co-location: the in-process adapter writes
`run_summary.json` into the run directory via a **shared `run_paths.run_dir`
helper** (the single source of truth for `<base>/runs/<run_id>`, also used by
the persistence adapter) — agreeing on *where* without depending on the
persistence *port*.

### D4 — Tracing is per-phase span aggregates (count / total / mean ms)

The tracing pillar is realized as **named spans** timed via the port's `span`
context manager and aggregated into `SpanStats` (count, total_ms, mean_ms) per
name. v1 instruments the dominant phases: `harness.run` and
`scorer.score_objective` (in `TrialRunner`) and `trial` (in `OptimizerDriver`),
which share one adapter instance so runner- and driver-level timings aggregate
together. This is the lightweight, dependency-free analogue of distributed
tracing — enough to answer "where did the time go" without span-context
propagation, which is the OTel concern deferred in D1.

## Reconsider Triggers

- **Logs/metrics leave the single-operator host** (enterprise scenario 2). OTel
  transport for traces and metrics becomes load-bearing; add an OTel adapter
  behind `ObservabilityPort` and an OTLP handler behind the logging layer. This
  is the same trigger as ADR 0015 MD2/MD6-B and the ADR 0020 egress deferral.
- **`asyncio` adoption.** `span` timing and `contextvars` correlation must be
  re-verified under the event loop (the ADR 0015 trigger applies here too).
- **Cross-run / fleet aggregation.** If summaries must roll up across runs, a
  real metrics store (or OTel metrics) replaces the per-run JSON artifact.

## Consequences

- **New domain types** `RunSummary` / `SpanStats`; **new port**
  `ObservabilityPort`; **new adapters** `InProcessObservability` /
  `NullObservability`; **new helper** `domain/run_paths.run_dir`
  (`PerTrialDirectoryAdapter._run_dir` now delegates to it).
- **`TrialRunner` and `OptimizerDriver`** gain an optional `observability`
  parameter (Null default); the existing run path is unchanged when it is unset,
  so all prior tests hold without modification.
- **New artifact `run_summary.json`** joins the run directory beside
  `run_config.json` / `run_events.jsonl` / `trial_manifest.jsonl`. It is *not*
  schema-version-stamped in v1 (it is a derived, forward-additive report, not a
  reloaded source of truth); promoting it into the ADR 0019 governed set is a
  follow-up if anything starts reading it back.
- **The run entry point is the natural next consumer.** `main.py` is still a
  placeholder and the driver is exercised only via tests/acceptance; whoever
  builds the run CLI wires one `InProcessObservability(base_dir=...)` into both
  `TrialRunner` and `OptimizerDriver` (alongside `configure_logging`).
- **OpenTelemetry stays out of the dependency set**, holding the lean-dependency
  posture (only `torch`/`botorch` from ADR 0016, ADR 0021's CPU lock).

## Related

- [ADR 0015 — Structured Logging Depth](0015-structured-logging-depth.md): the
  logging pillar this extends; its stdlib-only / OTel-deferred posture and its
  enterprise reconsider trigger are inherited here.
- [ADR 0013 — Driver run-event log](0013-driver-run-event-log.md): the run
  directory layout where `run_summary.json` lives.
- [ADR 0007 — Pi invocation lifecycle](0007-pi-invocation-lifecycle.md): the
  wallclock cap and the unattended-overnight-run scenario the summary serves.
- [ADR 0019 — Versioning and Compatibility](0019-versioning-and-compatibility-policy.md):
  why `run_summary.json` is kept out of the governed-schema set for now.
- Issues: `5eb` (this work), `ent` (ADR 0015 logging, done), `0ec` (MD6-B
  field-allowlist, enterprise-gated).
- Spike **S007** in `docs/implementation-plan.md` — closed by this ADR.
