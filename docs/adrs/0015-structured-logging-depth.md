# Title: 0015 - Structured Logging Depth

**Status:** Accepted

## Context

`pi-agent-space-wtw` landed a minimum viable structured logging layer:
`JsonFormatter` (stdlib, no new dependency), `configure_logging()`, and one
structured log call in `OptimizerDriver`. That covers the basics but leaves
eight engineering commitments and six architectural choices open.

This ADR records the commitments as binding and works through the
architectural choices so that the logging layer can be promoted from MVP to
production-grade ahead of Phase 5.2 / Phase 6's unattended overnight runs.

## Commitments (not options; binding regardless of must-decide outcomes)

The following are engineering obligations, not choices between alternatives.
They are accepted here without further debate and become acceptance criteria
for the implementation that closes this ADR.

1. **Bind global contextual metadata via `contextvars`.** `run_id` and
   `trial_id` are set in `contextvars.ContextVar` at the start of each run
   / trial and read by `JsonFormatter` to inject them into every log record
   automatically. No call site passes them explicitly via `extra`.

2. **Flat JSON to stdout/stderr only for transport.** Log lines are emitted
   as flat JSON strings to stdout or stderr. File durability is handled by
   the run-level `run.log` file (ADR 0013) or operator-side stream
   redirection — not by adding non-streaming sinks inside the library.

3. **Guaranteed fields on every record: `timestamp` (absolute ISO 8601 UTC),
   `level`, `logger`.** Already implemented in `JsonFormatter`. This
   commitment locks the field names so downstream tooling can rely on them.

4. **Exceptions captured via `logger.exception()`.** All `except` blocks
   that log use `logger.exception(...)` (not `logger.error(...)`) to include
   the full traceback in `exc_info`. `JsonFormatter` serialises it as a
   string field `"exc_info"`.

5. **`QueueHandler` isolation.** The main thread is not blocked by log I/O.
   `configure_logging()` routes records through a `logging.handlers
   .QueueHandler` + `QueueListener` pair so formatter and handler work run
   in a background thread. Matters for overnight unattended runs (ADR 0007)
   where a stalled file write must not delay trial timing.

6. **Module-level logger instantiation only.** All loggers are created at
   module level via `logging.getLogger(__name__)`. No logger is created
   inside a function or method. `optimizer_driver.py` already follows this;
   new modules must too.

7. **No propagation overrides.** `logger.propagate = False` is never called.
   The `pi_evaluator` root logger receives all records from child loggers via
   normal propagation; the `NullHandler` default is replaced only by
   `configure_logging()` at entry-point time.

8. **Third-party library loggers verified.** Before Phase 6 (surrogate model
   adds dependencies like `torch`/`botorch`/`scipy`), audit which third-party
   loggers emit at WARNING or above and confirm they propagate into the
   `pi_evaluator` root config or are explicitly silenced.

## Options Considered

### MD1 — Framework: stdlib logging vs structlog

**MD1-A: Keep stdlib `logging` + `JsonFormatter` (current).**
All Python programmers know the stdlib API; no new dependency; `dictConfig`
gives operator-configurable levels without code changes. Context binding uses
`LoggerAdapter` or `contextvars` directly with a custom filter.

**MD1-B: Migrate to `structlog`.**
`structlog` provides a native processor pipeline, first-class
`structlog.contextvars` for thread-safe context binding, and a cleaner
API for chaining transformations (redaction, sampling, enrichment). Cost:
new dependency; two logging APIs in the codebase during migration; some
third-party libraries still emit via stdlib `logging` and need a bridge.

### MD2 — Transport: stdout-only vs stdout + experiment-directory file

**MD2-A: stdout/stderr only.**
12-factor style — operators redirect the stream or run a sidecar agent.
The library has no file-writing responsibility. Tension: ADR 0013 expects
a `run.log` in the experiment base directory for local R&D durability; pure
stdout makes that an operator configuration task.

**MD2-B: stdout/stderr + `<base>/run.log` file via `configure_logging`.**
Current `configure_logging(log_file=...)` supports this. The run directory
(ADR 0013) provides the path; `OptimizerDriver` passes it at construction.
Local R&D workflows get durability without operator configuration. Cost: the
library writes files, which is a side effect that tests must stub or tolerate.

### MD3 — Context correlation: how `run_id` and `trial_id` reach every record

**MD3-A: `contextvars.ContextVar` read by a logging `Filter`.**
`RunContext.set(run_id=..., trial_id=...)` sets module-level `ContextVar`s.
A `Filter` subclass reads them and stamps each `LogRecord` before it reaches
the formatter. Thread-safe; works with `asyncio`; zero per-call overhead at
the log-site.

**MD3-B: `logging.LoggerAdapter`.**
`OptimizerDriver` wraps `logger` with `LoggerAdapter(logger, {"run_id": ...})`
and passes the adapted logger to `TrialRunner`. Each level of the call stack
wraps again with `trial_id`. Explicit but verbose; every constructor that
needs context must accept a logger parameter.

**MD3-C: `extra` kwargs at each call site.**
The simplest option — every `logger.warning(...)` passes
`extra={"run_id": ..., "trial_id": ...}`. Verbose, error-prone (easy to
forget on a new call site), but requires no infrastructure.

The X-Request-ID tracing concept from HTTP services maps onto this project
as `run_id` (run-scoped correlation) and `trial_id` (trial-scoped
correlation). MD3-A is the idiomatic Python equivalent.

### MD4 — JSON field naming convention: snake_case vs camelCase

**MD4-A: snake_case throughout.**
Consistent with Python conventions, existing event payload naming
(`cumulative_cost_dollars`, `threshold_fraction`, `run_id`), and the
`events.jsonl` / `final.json` field names. Already used in the MVP.

**MD4-B: camelCase throughout.**
Consistent with JSON/JavaScript conventions and many log aggregation tools
(Datadog, Elastic). Would require a camelCase translation layer in
`JsonFormatter` and diverge from the domain's snake_case event payloads.

### MD5 — Log level policy by environment

**MD5-A: `INFO` always; `DEBUG` via `LOG_LEVEL` environment variable.**
Simple operator override: `LOG_LEVEL=DEBUG pi-eval run ...`. The library
reads `os.environ.get("LOG_LEVEL", "INFO")` in `configure_logging` as the
default. Per-module granularity is available via the stdlib hierarchy if
needed.

**MD5-B: `INFO` in production, `DEBUG` in development via config file.**
A `logging.config.dictConfig`-compatible YAML/JSON file governs levels per
logger name. Requires a config file convention and a loading path.

**MD5-C: Per-logger granularity hardcoded.**
`optimizer_driver` logs at `DEBUG`; others at `INFO`. Determined at
code-write time, not at runtime. Inflexible for operators but zero
configuration surface.

### MD6 — PII scrubbing policy

**MD6-A: Call-site discipline (policy, no enforcement).**
Callers never log raw `system_prompt`, `template_values`, or API key values.
Structured `extra` fields carry identifiers (IDs, counts, costs) not content.
No runtime scrubbing — violations are caught in code review.

**MD6-B: Field-level allowlist in `JsonFormatter`.**
Only pre-approved field names pass through to the JSON output; unrecognised
fields are dropped or replaced with `"<redacted>"`. Adds a maintenance
burden (allowlist must be updated as new fields are added) but prevents
accidental PII leakage from a new call site.

**MD6-C: Pattern-based scrubbing in `JsonFormatter`.**
String values are scanned for known PII patterns (API key prefixes like
`sk-`, email-like strings) and replaced with `"<redacted>"`. Brittle —
pattern coverage is never complete, and false positives can redact legitimate
values (e.g. a `model` string that happens to start with a key-like prefix).

## Decision

The eight commitments above are binding. The six must-decide items resolve to
their context-indicated directions:

- **MD1 — Framework: MD1-A (keep stdlib `logging` + `JsonFormatter`).** No async
  surface yet; `contextvars` + a logging `Filter` (MD3) covers context binding
  without a `structlog` dependency. The Phase 6 reconsider-trigger was checked at
  acceptance — `torch`/`botorch` emit via stdlib `logging`, so a `structlog`
  bridge would add cost without simplifying anything today.
- **MD2 — Transport: MD2-B (stdout/stderr + `<base>/run.log`).** Consistent with
  ADR 0013's run-directory durability; `configure_logging(log_file=...)` already
  supports it. Tests stub or tolerate the file side effect.
- **MD3 — Correlation: MD3-A (`contextvars.ContextVar` read by a logging
  `Filter`).** `run_id`/`trial_id` are set once per run/trial and stamped onto
  every record; thread- and `asyncio`-safe, zero per-call-site cost. Realises
  commitment 1.
- **MD4 — Naming: MD4-A (snake_case).** Matches every existing event-payload and
  persisted field name.
- **MD5 — Level policy: MD5-A (`INFO` default; `DEBUG` via `LOG_LEVEL` env).**
  `configure_logging` reads `os.environ.get("LOG_LEVEL", "INFO")`. Simplest
  operator surface; per-module granularity remains available via the stdlib
  hierarchy.
- **MD6 — PII scrubbing: MD6-A (call-site discipline) for v1.** Structured
  `extra` fields carry identifiers, counts, and costs — never raw
  `system_prompt`, `template_values`, or key values; enforced in code review. The
  stronger field-allowlist (MD6-B) is **deferred** as a triggered follow-up
  gated on the enterprise deployment scenario, tracked together with the raw
  event-stream redaction concern (`pi-agent-space-28g`) so the redaction question
  lives in one place. Note MD6 governs the *logging* layer only; `events.jsonl`
  redaction (28g) is a separate persistence concern.

## Reconsider Triggers

- **Phase 6 adds ML dependencies** (`torch`, `botorch`). Audit MD1-B
  (structlog) again at that point — if the processor pipeline simplifies
  context binding across async surrogate calls, the dependency cost changes.
- **Enterprise deployment scenario** (three-scenario model, scenario 2).
  OpenTelemetry transport (MD2) and PII scrubbing (MD6-B) become load-bearing
  when logs leave the local R&D machine.
- **`asyncio` adoption.** If the trial runner or surrogate proposer moves to
  async I/O, verify that `QueueHandler` (commitment 5) and `contextvars`
  (MD3-A) remain correct under the event loop — `contextvars` propagates
  correctly into `asyncio.Task`s but not into `ThreadPoolExecutor` workers.

## Consequences

- A `RunContext` (module-level `ContextVar`s for `run_id`/`trial_id`) and a
  `Filter` that stamps them onto every record join `logging_config.py`;
  `OptimizerDriver`/`TrialRunner` set the context at run/trial boundaries instead
  of threading IDs through `extra`. The seam-level info logs already emitted by
  the tolerant reader (ADR 0019) and schema-version check gain `run_id`/`trial_id`
  for free once a run is in scope.
- `configure_logging` routes records through a `QueueHandler` + `QueueListener`
  (commitment 5) and reads `LOG_LEVEL` (MD5-A); it keeps the stdout handler and
  the optional `<base>/run.log` file handler (MD2-B).
- A codebase pass enforces the conventions: `logger.exception()` in logging
  `except` blocks (commitment 4), module-level loggers only (6), no `propagate`
  overrides (7), and a third-party logger audit covering
  `torch`/`botorch`/`gpytorch`/`scipy` (commitment 8) — which currently surface
  numerical warnings during tests.
- `structlog` is **not** taken as a dependency; the lean-dependency posture
  (only `torch`/`botorch` from ADR 0016) holds.
- Implementation is tracked under `pi-agent-space-ent`; the deferred MD6-B
  allowlist is its own follow-up.
