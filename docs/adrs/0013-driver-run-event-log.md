# Title: 0013 - Driver-run event log

**Status:** Accepted

## Context

`OptimizerDriver` manages concerns that cross trial boundaries: a per-run
cost cap (ADR 0005), a circuit breaker with two trip conditions (ADR 0007),
and future run-level metadata (run ID, wall-clock start/end, total proposals
dispatched). Currently these surface in two ways only:

- **Python `logging`** — `logger.warning(...)` for the cost-cap warning;
  no structured output.
- **`OptimizerResult.halted_reason`** — in-memory string (`"budget"`,
  `"per_run_cost_cap"`, `"circuit_breaker_errors"`, `"circuit_breaker_time"`,
  `"exhausted"`); never written to disk.

The per-trial persistence layout (ADR 0003) anchors every durable record to
a trial directory (`<base>/<trial_id>/events.jsonl`). Run-level events have
no trial to hang off of. Emitting them into the closest trial's `events.jsonl`
would couple driver concerns to an arbitrarily-chosen trial (whichever
happened to be in flight when the event fired) — semantically wrong.

Phase 5.2 introduces the `pi-eval score` CLI, which opens an existing trial
directory and appends a retroactive event. For the CLI to be well-defined,
the filesystem layout must have a settled answer for *where driver-level
records live* — otherwise 5.2 would have to invent one ad hoc.

This spike's goal is to determine whether a durable driver-level record is
warranted, and if so, what shape it takes.

### Settled sub-decisions

Two decisions have been made that constrain the option space:

**1. "Run" enters the domain vocabulary.**
The optimizer-level envelope around a set of trials is called a **run**.
This distinguishes it from the Pi harness concept of a *session*
(created/resumed via `--session-id`, Pi-internal). A run has a globally
unique run ID (UUID). The existing `OptimizerDriver.run()` method and
`OptimizerResult` are the current in-memory expression of this concept;
the question S001 is asking is what durable artifact, if any, represents
a run on disk.

**2. Re-runs produce new trial IDs.**
If a trial is re-run (e.g. after an interrupted session, or for manual
re-evaluation), the re-run is a new trial with its own ID. The
trial-to-run relationship is therefore many-to-one: each trial belongs
to exactly one run; a run may have many trials; no trial ID is reused
across runs. This keeps trial IDs as stable, globally unique keys and
avoids the ambiguity of "which invocation produced this result."

### New capability: `--session-id`

The Pi harness now accepts `--session-id <id>`, which creates or resumes a
named, project-local session across invocations. A session persists the
agent's conversation context — tool call history, prior outputs — so a
resumed invocation picks up where the previous one left off rather than
starting cold.

This introduces a new design axis orthogonal to filesystem layout: whether
the optimizer assigns sessions at run granularity (one session for all
trials) or trial granularity (one session per trial). The two choices have
qualitatively different semantics:

- **One session per run.** The agent accumulates context across all trials
  in the run — it can observe that previous configurations failed or hit
  cost caps, and adapt. This is agent-level learning within the run. It
  directly conflicts with ADR 0006's independence assumption: trials in the
  same run are no longer independently drawn samples, which invalidates the
  surrogate model's i.i.d. premise.
- **One session per trial.** The agent starts fresh for each trial, preserving
  independence. The session is useful only for retries (ADR 0007 B1 retries
  resume the same session rather than re-materializing cold context).

Options R5 and R6 below explore each granularity. R7 uses session ID as a
thin correlation key without relying on Pi's session log as the durable
record.

## Options Considered

### R1 — Run-level `run_events.jsonl` at the base directory

A new append-only file alongside the trial subdirectories:

```
<base>/
  run_events.jsonl          ← new
  <trial_id_1>/
    events.jsonl
    final.json
    ...
  <trial_id_2>/
    ...
```

Driver appends structured events here: `run_cost_cap_warning`,
`run_cost_cap_exceeded`, `circuit_breaker_tripped`, and a `run_started`
/ `run_halted` pair that brackets the session. The `run_halted` event's
payload carries `halted_reason`.

- **Pros:** Mirrors the per-trial event-stream discipline the project already
  uses; append-only; the record grows incrementally rather than being written
  only at run-end. Tools reading trial directories can also find the run
  context without an out-of-band channel.
- **Cons:** Adds a new file to the layout that every consumer must learn
  about. `PersistencePort` grows a new method (`append_run_event`), and the
  in-memory stub must implement it. Run-level events and trial-level events
  live in different files with no shared reader path today.

### R2 — `run_summary.json` written at run end

A single JSON document written atomically (temp-then-rename, per ADR 0003
precedent) when `OptimizerDriver.run()` returns:

```json
{
  "halted_reason": "per_run_cost_cap",
  "trials_completed": 7,
  "cumulative_cost_dollars": 4.21,
  "wall_clock_start": "...",
  "wall_clock_end": "..."
}
```

- **Pros:** Minimal surface — one new file, written once, no port change
  beyond `save_run_summary(...)`. The `pi-eval score` CLI doesn't need it
  (it operates on trials, not runs); this serves human-facing tooling and
  future dashboards.
- **Cons:** Loses mid-run durability — if the driver process is killed, no
  `run_summary.json` exists. Not an event stream; no incremental record of
  warnings that fired during the run. If two warnings fire, only the final
  state is visible.

### R3 — Python logging only; no new filesystem artifact

Run-level events go to Python's structured logging. If operators need
durable records, they configure a file handler (e.g., `FileHandler` + JSON
formatter). The `halted_reason` in `OptimizerResult` satisfies the driver's
internal accounting; callers who need it persist it themselves.

- **Pros:** Zero new filesystem surface. No changes to `PersistencePort`.
  The `pi-eval score` CLI (Phase 5.2) doesn't consult driver logs; this
  question is orthogonal to the CLI design.
- **Cons:** Makes run-level observability an operator concern rather than a
  framework concern. Post-hoc analysis of "why did this run halt?" requires
  log files that may have rotated, rather than a stable artifact in the
  experiment directory.

### R4 — Dissolve: Phase 5.2 does not require this decision

The `pi-eval score` CLI operates on individual trial directories. Its append
path (Phase 5.2) writes into `<base>/<trial_id>/events.jsonl` and
`final.json`. No driver-level event record is consulted or written by the
CLI. S001's premise — "Phase 5.2 needs a place for non-trial-scoped events"
— may be a false dependency: Phase 5.2 can be designed and implemented
without settling where driver-run events live.

If R4 is accepted, S001 becomes a Phase 6 concern (when the surrogate
model needs run-level cost history to inform bootstrap decisions) or a
Phase 7 concern (when a `pi-eval runs` CLI surfaces run history to
operators). The row is removed from the Open Spikes table; a new spike is
opened at the appropriate phase boundary.

- **Pros:** Unblocks Phase 5.2 immediately. Does not force a filesystem
  layout decision before the use cases are clear.
- **Cons:** If Phase 6's surrogate proposer needs run-level history, the
  layout question returns at a less convenient time.

### R5 — One Pi session per run; Pi session log as the run-level record

The driver generates a `run_id` (e.g. a UUID) before the first trial.
Every `CliSubprocessAdapter.run()` call passes `--session-id <run_id>`.
Pi persists the session; the accumulated conversation log is the durable
cross-trial record. Driver-level events (cost cap warning, circuit breaker
trip) are injected as context messages into the session before the next
trial starts — e.g., `"[driver] per-run cost cap warning: $3.20 of $4.00
used"` — so the session log captures both agent activity and driver
concerns in one place.

- **Pros:** No new filesystem artifact on our side; Pi owns the durability.
  Driver events and agent events are co-located in the session log, which
  is natural for post-hoc replay. The agent can adapt mid-run (seeing past
  trial outcomes in its context window) — which may itself be desirable for
  some R&D workflows.
- **Cons:** Violates ADR 0006's independence assumption: trials within the
  same run are no longer independent samples; the surrogate GP's i.i.d.
  premise breaks. Pi's session format is Pi-internal; our tooling cannot
  read it without parsing Pi's output format. Cost-cap and circuit-breaker
  events become natural-language injections rather than structured events,
  making them hard to query programmatically. If the session log is
  inaccessible (Pi stores it opaquely), R5 degenerates to R3.

### R6 — One Pi session per trial; session resumption for ADR 0007 retries

Each trial uses `--session-id <trial_id>`. The session ID is stored in
`config.json` alongside the trial ID. For ADR 0007 B1 retries, the retry
invocation passes the same `--session-id <trial_id>`, resuming the agent's
how context rather than starting cold against the same materialized workspace.

This option does **not** resolve S001 on its own — driver-level run events
still need a home (R1–R4). R6 is most useful combined with R1 or R2: R6
addresses retry semantics; R1/R2 addresses run-level durability.

- **Pros:** Preserves trial independence (ADR 0006 holds). Retry semantics
  improve significantly — the retried agent remembers what it attempted in
  the first pass, reducing the chance of the same error recurring. Session
  ID in `config.json` is a natural audit trail for which Pi session produced
  which trial.
- **Cons:** Doesn't provide a run-level event log. Retry-resume semantics
  are only useful once `CliSubprocessAdapter` actually wires `--session-id`
  through; `retry_budget` is currently declarative-only (see module
  docstring). Adds a Pi-dependency to the persistence schema
  (`config.json` grows a `pi_session_id` field).

### R7 — Session ID as a run correlation key embedded in trial events

The driver generates a `run_id` and records it in each trial's `configured`
event payload (`"run_id": "<uuid>"`). `CliSubprocessAdapter` passes
`--session-id <run_id>` so Pi also groups agent activity by run. No Pi
session log is read by the optimizer; driver events continue via Python
logging (R3). The `run_id` in `configured` events is the sole correlation
artifact.

Post-hoc tools reconstruct which trials belong to which run by filtering
`configured` events for `run_id`. The `pi-eval score` CLI (Phase 5.2) can
read the `run_id` without a run-level file.

- **Pros:** Thinnest possible surface — one extra field in an existing
  event; no new files, no `PersistencePort` changes, no Pi session log
  dependency. Run correlation is recoverable from the existing
  `events.jsonl` files without a new artifact. Compatible with R4
  (dissolve) if S001's run-level event log question is deferred.
- **Cons:** With plain Python logging the `run_id` is a grouping key only
  — circuit breaker trips and cost cap warnings are unstructured strings,
  not queryable fields. *With structured logging* (see `pi-agent-space-wtw`)
  this con collapses: driver events carry `run_id` as a structured field
  and, if the file handler writes to `<base>/run.log`, are co-located with
  the experiment directory and `jq`-queryable. The remaining con after
  structured logging lands: the log file's path is handler-configured
  (operator concern), not framework-guaranteed the way R1's
  `<base>/run_events.jsonl` is. Any Phase 6 surrogate code that needs
  programmatic access to run-level history would read from a
  handler-configured path rather than a stable `PersistencePort` API —
  less clean than R1 if that consumer exists, but viable if it doesn't.

### R8 — Run as a first-class domain entity with its own directory

`Run` joins the domain vocabulary as a persistent entity alongside `Trial`.
A run directory lives under a `runs/` subdirectory at the base:

```
<base>/
  runs/
    <run_id>/
      run_config.json       ← slot space, cost caps, eval suite ref, version vector
      run_events.jsonl      ← run_started, cost_cap_warning, circuit_breaker_tripped,
                               run_halted (with halted_reason)
      trial_manifest.jsonl  ← one line per trial: {trial_id, status, timestamp}
                               written incrementally as trials complete or fail
  <trial_id_1>/
    config.json             ← gains a run_id field
    versions.json
    events.jsonl
    final.json
  <trial_id_2>/
    ...
  frontier.json
```

`trial_manifest.jsonl` is append-only (like `events.jsonl`): one line per
trial, written when the trial is dispatched and updated when it closes.
On interruption, the manifest distinguishes completed trials (have a
`final.json`) from in-flight trials (dispatched but no `finalized` event)
from not-yet-started trials — which is what resilience requires.

The trial's `config.json` gains a `run_id` field, making the
trial-to-run link explicit and navigable without reading the run directory.

`PersistencePort` gains: `create_run(run_id, config)`,
`append_run_event(run_id, event)`, `record_trial_dispatched(run_id,
trial_id)`, `record_trial_closed(run_id, trial_id, outcome)`.

Resilience paths:
- **Resume**: read `trial_manifest.jsonl`, skip completed trials (have
  `finalized` event in their `events.jsonl`), clean up or re-propose
  in-flight trials (new trial ID per the re-run decision above).
- **Clean up**: read the manifest, remove in-flight trial directories
  whose data is partial, mark the run as `abandoned` in
  `run_events.jsonl`.

Pi harness sessions (R5/R6/R7) are orthogonal: a run's `run_config.json`
can record the Pi `--session-id` strategy chosen without conflating the
two concepts.

- **Pros:** Fully resolves S001 with a stable, framework-guaranteed
  layout. Answers all the operator question categories from the brainstorm:
  retrospective (run_events.jsonl), decision support (trial_manifest +
  frontier.json), operational monitoring (run_events.jsonl live), audit
  (run_config.json + trial run_id field). Resilience is first-class, not
  bolted on. R7's remaining weakness (handler-configured path) disappears —
  the run directory is always at `<base>/runs/<run_id>/`. Structured
  logging (pi-agent-space-wtw) becomes a complement, not a substitute.
- **Cons:** Largest surface of the options — new domain type, new
  persistence methods, new directory layout, new `config.json` field.
  `PersistencePort` grows four methods; every adapter (including in-memory
  stubs) must implement them. Migration: existing experiment directories
  have no `runs/` subdirectory; tooling that reads `<base>/` must handle
  both old and new layouts during a transition window.

## Decision

**R8 — Run as a first-class domain entity with its own directory.**

The layout, port methods, and resilience paths are as described in R8
above. Two sub-decisions are incorporated:

- **"Run" enters the domain vocabulary.** The optimizer-level envelope is
  a `Run`; Pi's harness `--session-id` concept is a distinct thing called
  a *session*. The two may share an ID value (e.g. R7 embeds `run_id` as
  the Pi session ID) but are never conflated in naming.
- **Re-runs produce new trial IDs.** The trial→run relationship is
  many-to-one with a single `run_id` foreign key on the trial side.

Migration concern is deferred: no v1 experiment directories exist yet, so
backward compatibility with the old flat layout is not required at this
time.

## Reconsider Triggers

- **`PersistencePort` grows beyond ~8 methods total.** If the combined
  trial + run surface becomes unwieldy, split into `TrialPersistencePort`
  and `RunPersistencePort`. The hexagonal boundary stays the same; the
  interface is refactored, not the concept.
- **`runs/` subdirectory causes tooling friction.** If a future `pi-eval
  runs` CLI finds it awkward to enumerate runs alongside trials from
  `<base>/`, revisit whether runs and trials should be peers in a flat
  namespace (with a naming convention to distinguish them) rather than
  in a subdirectory.
- **Migration becomes real.** When v1 ships and experiment directories
  exist in the wild, add a migration path that synthesises a stub run
  record from the flat trial directories (run_id = sentinel, no
  run_events.jsonl, trial_manifest reconstructed from trial directories).

## Consequences

- `Run` is a new domain concept. At minimum: a `RunConfig` frozen
  dataclass (slot space, cost caps, eval suite ref, version vector, Pi
  session strategy) and a `RunEvent` type (or reuse `TrialEvent` with
  run-scoped phase names). These live in `domain/types.py` or a new
  `domain/run.py` if file size warrants.
- `PersistencePort` gains four methods:
  - `create_run(run_id, config: RunConfig) -> None`
  - `append_run_event(run_id, event: RunEvent) -> None`
  - `record_trial_dispatched(run_id, trial_id) -> None`
  - `record_trial_closed(run_id, trial_id, outcome: Outcome) -> None`
- `PerTrialDirectoryAdapter` implements the four new methods. The run
  directory layout is `<base>/runs/<run_id>/` with `run_config.json`,
  `run_events.jsonl`, and `trial_manifest.jsonl`.
- Every in-memory stub adapter used in tests must also implement the four
  methods (no-ops are acceptable for tests that don't exercise run-level
  behaviour).
- `Trial.config.json` (written by `save_trial`) gains a `run_id` field.
  `PerTrialDirectoryAdapter.save_trial` is updated accordingly; existing
  tests that assert on `config.json` shape are updated.
- `OptimizerDriver` generates a `run_id` (UUID) at construction time or
  at `run()` entry, calls `create_run(...)` before the trial loop, emits
  `run_started` and `run_halted` events via `append_run_event`, and calls
  `record_trial_dispatched` / `record_trial_closed` around each
  `runner.run_trial()` call.
- `OptimizerResult` gains a `run_id: str` field.
- The `frontier.json` written by `save_frontier` is unchanged in location
  (`<base>/frontier.json`); it is a derived view over all trials regardless
  of run and does not move into the run directory.
- Structured logging (`pi-agent-space-wtw`) remains a complement: it
  provides a human-readable stream; `run_events.jsonl` is the
  machine-readable record for programmatic consumers.
