# Title: 0017 - Typed Event-Payload Model for the Trial/Run Event Streams

**Status:** Proposed

> Spike in progress; decision target **Phase 7** (first post-v1 phase). Decision, Consequences, and Reconsider Triggers read `TBD` until the spike closes.

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

## Versioning interaction (why this is a Phase 7 / post-v1 item)

Options 1–3 all touch how the persisted event streams are read and written. Even the "format-preserving" options (1, 2) change the *contract* between code versions: once payloads are typed, a field rename or a new required field is a format-compatibility event for any trial directory already on disk. That makes this decision a dependency of — not independent from — the project's **versioning / compatibility policy**: what does a SemVer bump *mean* for the on-disk trial/event schema, and do we promise to read trial directories written by older versions? That policy question is itself unresolved (it belongs on the Phase 7 list) and should be settled, or at least sketched, before a typed-payload model that affects the wire format is accepted. The `RawTelemetry` half did not raise this because Pi owns that schema and we never persist it.

## Decision

TBD — spike open; decision target Phase 7.

## Consequences

TBD.

## Reconsider Triggers

TBD. (Candidate signals to fold in as the spike develops: a silent payload-key drift bug reaching a consumer; a second consumer of `metric_record`/`eval` payloads appearing; a decision to persist events in a non-JSONL backend; resolution of the SemVer/compatibility policy.)

## Related

- ADR 0003 (per-trial persistence layout) — defines the on-disk event-stream format this would type.
- ADR 0011 (outcome classifier / event stream as single source of truth) — the derive-don't-store discipline the typed model must respect.
- ADR 0012 (capability profile and metric events) — defines the `metric_record`/`eval` payload fields the consumer reads.
- ADR 0013 (driver-run event log) — the `run_events.jsonl` stream sharing the `Event` shape.
- ADR 0016 (surrogate framework) — precedent for taking a heavyweight runtime dependency (relevant to Option 3).
- `pi-agent-space-3kz` — the originating issue (RawTelemetry half done; this is the remaining half).
- `domain/telemetry.py` — the typed-view pattern already applied to the raw-Pi half, a possible template for Option 1.
