# Title: 0017 - Typed Event-Payload Model for the Trial/Run Event Streams

**Status:** Accepted

## Context

The optimizer's durable record is an event stream: per-trial events in `events.jsonl` (ADR 0003) and per-run events in `run_events.jsonl` (ADR 0013). All events share one shape — `Event(phase: str, timestamp: str, payload: dict)` (`domain/types.py`; `TrialEvent`/`RunEvent` are aliases of `Event`). The `payload` is an untyped `dict`.

Issue `pi-agent-space-3kz` flagged two untyped boundaries. The **`RawTelemetry.events`** half is resolved: Pi's raw JSON stream is now parsed once into a typed `AssistantMessage` view (`domain/telemetry.py`), so the scorer and lifecycle classifier read typed fields instead of digging through dicts. That half was a clean, contained simplification because the parse has exactly one shape and one set of consumers.

The **`Event.payload: dict`** half is what this ADR addresses, and it is genuinely architectural rather than a mechanical refactor:

- **Stringly-typed producer/consumer coupling.** `trial_runner.py` constructs payloads with bare string keys (`"problem_id"`, `"metric_name"`, `"value"`, `"difficulty"`, …); `domain/capability_profile.py` reads them back with `event.payload.get("problem_id")` and friends. A rename or typo on either side fails silently — nothing binds the producer and consumer to the same schema.
- **Heterogeneous stream.** `capability_profile` projects over a *mixed* stream, filtering by `phase` before reading payload fields. Whatever typing we adopt must still dispatch on phase; it cannot assume a single payload shape.
- **Producer writes a superset.** `eval` payloads carry `exit_code` (diagnostic) that the profile ignores; `metric_record` carries `n_samples`. Naive per-phase dataclasses that mirror only what the consumer reads would drop fields the producer legitimately records.
- **`payload` is a persisted wire contract.** ADR 0003 fixes the on-disk JSON layout, and ADR 0011 makes the event stream the single source of truth (derive-don't-store). Any typed model must serialize to/from the same JSON without changing what older trial directories on disk mean — i.e., it is a *format-compatibility* concern, not just an in-memory typing concern.

The phases were built as tracer bullets — each cut end-to-end through every layer — which kept the system coherent but left the event payload as the one boundary still expressed as a free dict on both ends. The question this ADR closes: **what typed model, if any, should replace `Event.payload: dict`, and how does it serialize across the persisted event streams without breaking format compatibility?**

## Options Considered

### 1. Per-phase frozen dataclasses + manual `from_payload`/`to_payload`

Define a dataclass per event phase that carries payload data the domain cares about (e.g. `MetricRecord(problem_id, metric_name, value, n_samples)`, `EvalRecord(problem_id, difficulty, exit_code)`), plus a `parse(event) -> EventPayload | None` that dispatches on `phase`. Producers build payloads via `asdict(record)`; consumers parse once at the top of the loop.

* **Pros:** No new dependency (consistent with the project's lean posture — the only runtime dep is BoTorch/torch from ADR 0016). Field names live in one place; producer and consumer bind to the same dataclass. Serialization is `asdict`/`**` over plain JSON, so the on-disk format is unchanged.
* **Cons:** Hand-rolled `from_payload` parsing per phase is boilerplate. No runtime validation of data read from disk (a corrupt `value` still surfaces as a type error downstream, not at the boundary). A sealed union over phases needs a discriminated-union pattern Python expresses only awkwardly (`match` on a `phase` literal, or `typing.assert_never`).

### 2. `TypedDict` union (structural, no runtime cost)

Express each phase's payload as a `TypedDict`, unioned and discriminated on a `phase` literal. `payload` stays a `dict` at runtime; the types are purely static.

* **Pros:** Zero runtime overhead and zero serialization change — `payload` *is* a dict, so on-disk format and persistence code are untouched. `ty` checks producer and consumer against the same `TypedDict`. Smallest diff of the typed options.
* **Cons:** No runtime validation (TypedDicts are erased). `.get()` still type-checks as `T | None`, so the defensive-read ergonomics improve only modestly. Discriminated `TypedDict` unions have rough edges in current type checkers.

### 3. Pydantic models at the boundary

Model each payload as a Pydantic class; validate when reading events back off disk (`load_trials`) and when constructing them.

* **Pros:** Runtime validation at the persistence boundary — malformed or schema-drifted `events.jsonl` fails loudly where it is read, not deep in `capability_profile`. Mature (de)serialization, discriminated unions, and schema-evolution tooling.
* **Cons:** A second heavyweight runtime dependency (after torch). Validation cost on every event load (the stream can be large). Heavier than the problem demands for data *we* wrote microseconds earlier; the validation value is mostly at the read-from-disk edge, which is also where it costs most.

### 4. Status quo — keep `payload: dict` with defensive `.get()`

Leave the boundary untyped; rely on tests and the `metric_record` event-shape assertions (Phase 4) to catch drift.

* **Pros:** Zero work, zero risk, no format question. The defensive reads are arguably *appropriate* for a robust projection over a heterogeneous, possibly-partial stream.
* **Cons:** Preserves the silent producer/consumer coupling that motivated `3kz`. The boundary stays the least-typed surface in an otherwise typed domain.

## Versioning interaction (why this is a Phase 7 / schema-governance item)

Options 1–3 all touch how the persisted event streams are read and written. Even the "format-preserving" options (1, 2) change the *contract* between code versions: once payloads are typed, a field rename or a new required field is a format-compatibility event for any trial directory already on disk. That makes this decision a dependency of — not independent from — the project's **versioning / compatibility policy**: what does a SemVer bump *mean* for the on-disk trial/event schema, and do we promise to read trial directories written by older versions? That policy question is now resolved by **ADR 0019** (versioning & compatibility policy, Accepted): within a major version, minor bumps are additive-only and readers are tolerant (newer-reads-older guaranteed via defaults; older-reads-newer drops-and-logs unknown fields). Under that policy the wire-format concern is bounded — a typed payload that only *adds* fields with defaults stays compatible — so this ADR is no longer gated and can proceed to a decision among Options 1–4. The `RawTelemetry` half did not raise this because Pi owns that schema and we never persist it.

## Decision

**Option 1 — per-phase frozen dataclasses with a phase-dispatching parse.** This
mirrors the pattern already shipped for the `RawTelemetry` half of `pi-agent-space-3kz`
(`domain/telemetry.py`'s `AssistantMessage`), so both halves of that issue close
with one idiom rather than two.

Concretely:

- **A frozen dataclass per emitted phase**, in a new `domain/event_payloads.py`:
  `Configured(package_model)`, `EvalRecord(problem_id, difficulty, exit_code)`,
  `MetricRecord(problem_id, metric_name, value, n_samples=1)`,
  `CostCapWarning(scope, cap_usd, cumulative_cost_dollars, fraction)`,
  `BoundaryViolation(reason, problem_id=None, timeout_seconds=None, cap_usd=None,
  cumulative_cost_dollars=None)`, `Finalized(tokens_consumed, cost_dollars,
  validation_pass_rate, quality_score, outcome)`. All phases the producer emits
  are modelled — not just the two `capability_profile` reads today — so producer
  and consumer bind to the *same* names and the coupling is closed on both ends.
  `boundary_violation`'s two shapes (timeout vs. cost cap) collapse into one
  dataclass discriminated by `reason`, with the shape-specific fields optional.

- **A sealed union and a single dispatcher.** `EventPayload = Configured | EvalRecord
  | … ` and `parse(event: Event) -> EventPayload | None`, matching on `event.phase`.
  Consumers (`capability_profile`) call `parse` once at the top of the loop instead
  of digging through `.get()` ladders; an unknown phase returns `None`.

- **Producers construct the dataclass and serialize via `asdict`.** The on-disk
  JSON is byte-for-byte unchanged (ADR 0003 layout preserved); only the in-memory
  construction at the ~7 `trial_runner` emit sites becomes typed.

- **`parse` reuses the ADR 0019 tolerant constructor** (`pi-agent-space-963`): each
  per-phase parse is `_tolerant(cls, event.payload, where=phase)`, so unknown
  fields are dropped-and-logged (forward-compat, ADR 0019 D4) and absent
  additive fields fall back to dataclass defaults (backward-compat, D3). No second
  parsing mechanism is introduced — the typed model and the versioning policy share
  one seam.

**Why not the alternatives.** Option 2 (`TypedDict`) leaves payloads as runtime
dicts — the lone structural-only type in an otherwise all-frozen-dataclass domain —
and barely improves the `.get() -> T | None` ergonomics that motivated the issue.
Option 3 (Pydantic) adds a second heavyweight runtime dependency whose headline
value, read-boundary validation, is now largely subsumed by the ADR 0019 tolerant
reader. Option 4 (status quo) leaves the producer/consumer key coupling that
`3kz` exists to close.

## Consequences

- A new `domain/event_payloads.py` holds the per-phase dataclasses, the
  `EventPayload` union, and `parse`. `Event.payload` *stays* `dict` on the
  `Event` dataclass and on disk — the typing is a parse/build layer over it, not
  a change to `Event`'s field type — so persistence and the wire format are
  untouched.
- The ~7 `trial_runner` emit sites build a dataclass and `asdict` it; the bare
  dict literals go away, binding producer to the schema. `capability_profile`
  reads `parse(event)` results, dropping its `.get()` + None-skip ladders.
- Adding a payload field is now an *additive minor* (ADR 0019 D5): give the
  dataclass field a default; old files read via the default (D3), older readers
  drop the new key (D4). A rename/removal is a major bump.
- Depends on the ADR 0019 tolerant seam (`pi-agent-space-963`) being in place so
  `parse` has a `_tolerant` to call; the typed-payload work (tracked on `3kz`)
  sequences after it.
- The boundary-violation modelling choice (one dataclass, `reason`-discriminated,
  optional shape fields) means a consumer must branch on `reason` to know which
  optionals are populated — acceptable, since no structural consumer reads
  boundary-violation payloads today.

## Reconsider Triggers

- A phase's payload grows a genuinely *required* second shape that optional fields
  model awkwardly → consider splitting that phase's dataclass into a sub-union.
- A second consumer needs runtime *validation* (not just typing) of payloads read
  off disk → revisit Option 3 for that boundary specifically (the tolerant reader
  drops unknowns but does not assert field *types*).
- A decision to persist events in a non-JSONL backend → the `asdict`/`_tolerant`
  serialization assumption is revisited (also an ADR 0019 trigger).
- The per-phase `match` dispatch accumulates enough arms to be unwieldy → consider
  a registry keyed by phase literal.

## Related

- ADR 0003 (per-trial persistence layout) — defines the on-disk event-stream format this would type.
- ADR 0011 (outcome classifier / event stream as single source of truth) — the derive-don't-store discipline the typed model must respect.
- ADR 0012 (capability profile and metric events) — defines the `metric_record`/`eval` payload fields the consumer reads.
- ADR 0013 (driver-run event log) — the `run_events.jsonl` stream sharing the `Event` shape.
- ADR 0016 (surrogate framework) — precedent for taking a heavyweight runtime dependency (relevant to Option 3).
- `pi-agent-space-3kz` — the originating issue (RawTelemetry half done; this is the remaining half).
- `domain/telemetry.py` — the typed-view pattern already applied to the raw-Pi half, a possible template for Option 1.
