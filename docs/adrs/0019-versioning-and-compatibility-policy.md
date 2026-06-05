# Title: 0019 - Versioning & Compatibility Policy for On-Disk Schemas

**Status:** Accepted

## Context

`pi-agent-space` persists durable artifacts as JSON on disk: the per-trial
4-file layout (`config.json`, `versions.json`, `events.jsonl`, `final.json`;
ADR 0003), the driver-run event log (`run_events.jsonl`; ADR 0013), and the
frontier file. ADR 0011 makes the event stream the single source of truth
(derive-don't-store), so these files *are* the record — not a cache of it.

This policy is the **schema-governance umbrella** item on the Phase 7 list
(spike S005) and the explicit **gate on ADR 0017** (typed event-payload model):
that ADR cannot accept a typed model that touches the wire format until we have
said what a version bump *promises* about reading data written by older versions.
Two facts frame the decision:

- **There is no schema-version stamp on disk today.** `versions.json` carries
  the `VersionVector` — *which package was under test* (model, prompt, …) — not
  *what format the file is*. Readers do `Model(**json)` and raise `TypeError` on
  any unexpected key, so the current de-facto policy is "exact-match or crash."
- **v1 is pre-1.0 and R&D-scoped.** The project is at `0.1.0`, and v1 targets
  the R&D-synthetic deployment scenario, not long-lived enterprise persistence.
  An over-strong durability promise would be premature; a *mechanism* that lets
  us make graduated promises is what we need.

The question this ADR closes: **what does a SemVer bump mean for the on-disk
schemas, and what cross-version read compatibility does a release promise?**

## Decision

A **one-way, additive, tolerant-reader** policy, scoped within a major version.

### D1 — Stamp a `schema_version` on every trial directory

Each trial directory carries a single `schema_version` string in `config.json`,
governing all four files as one unit (a trial directory is produced atomically by
one run at one version, so one stamp is correct; see ADR 0003). The value mirrors
the release SemVer **`MAJOR.MINOR`** at write time (patch omitted — see D2).
`config.json` is the required, read-first file in `load_trials`, so no new file
is introduced. The run-event log is stamped the same way in its own header record.

### D2 — Schema changes ride **minor** bumps; patch never changes schema

A change to any persisted schema requires at least a **minor** version bump. A
patch release (`1.0.0 → 1.0.1`) must not alter on-disk shape; that is why the
stamp omits patch.

### D3 — Backward read is **guaranteed** within a major (newer reads older)

A reader at `MAJOR.m` reads any file written by `MAJOR.k` for `k ≤ m`.
Mechanically: every field a later minor adds **must have a default**, so its
absence in an older file is well-defined. This is the load-bearing guarantee.

### D4 — Forward read is **best-effort and lossy** within a major (older reads newer)

A reader at `MAJOR.k` reading a `MAJOR.m` file (`m > k`) **must ignore** keys it
does not recognize rather than failing, and **log each ignored key at info**
(`file newer than reader`). This is the *tolerant reader / must-ignore* rule. It
is only safe because of D5.

### D5 — Minor versions are **additive-only**

Within a major version, a minor may only **add** fields (with defaults; D3).
Renaming, removing, or redefining the meaning of an existing field is a
**breaking** change and requires a **major** bump. This is the rule contributors
follow, and it is what makes D4 safe: must-ignore rescues a reader from fields it
never knew about, but not from a field it *relied on* being renamed away.

### D6 — Cross-**major** read compatibility is deferred

This ADR commits only to within-major compatibility (D3/D4). What a reader at
`2.x` promises about `1.x` files — migration, a compatibility shim, or "previous
major is unreadable" — is left to a future ADR opened when the first major bump
is on the horizon. v1 does not over-promise here.

### D7 — `0.x` runs the machinery without the formal guarantee

While pre-1.0, the schema may change freely (standard SemVer `0.x` semantics):
D3/D4/D5 are **not** contractually guaranteed across `0.x` minors. But the stamp
(D1) and the tolerant-reader seam (D4) are adopted **now**, so `1.0` inherits a
working, exercised mechanism rather than a policy on paper. `0.x` files stamp
their real `MAJOR.MINOR` (e.g. `"0.1"`).

### D8 — The `VersionVector` axis stays independent

The `schema_version` (wire format) and the `VersionVector` (package identity
under test) are orthogonal axes and evolve on separate tracks. However, the
tolerant-reader *behavior* of D4 is a general read-**boundary** discipline and
applies uniformly — including to `versions.json` — even though the version
*number* it carries is independent.

## Example

A metric_record event line, written by **1.0**:

```json
{"phase": "metric_record", "timestamp": "2026-06-05T17:02:11Z",
 "payload": {"problem_id": "p3", "metric_name": "pass_rate", "value": 0.83, "n_samples": 12}}
```

**1.1** adds an additive `unit` field (a minor bump, D2/D5):

```json
{"phase": "metric_record", "timestamp": "2026-06-05T17:02:11Z",
 "payload": {"problem_id": "p3", "metric_name": "pass_rate", "value": 0.83, "n_samples": 12, "unit": "fraction"}}
```

The trial directory's `config.json` stamps the writer (D1):

```json
{ "schema_version": "1.1", "trial_id": "t-0007", "run_id": "r-2026-06-05-a", "...": "..." }
```

**Backward (D3) — 1.1 reads the 1.0 line:** `unit` is absent; the typed model
defaults it.

```python
@dataclass(frozen=True)
class MetricRecord:
    problem_id: str
    metric_name: str
    value: float
    n_samples: int
    unit: str = "fraction"   # added in 1.1; default makes 1.0 files readable
```

**Forward (D4) — 1.0 reads the 1.1 line:** `unit` is unknown; it is dropped and
logged. The tolerant seam replaces the brittle `Model(**json)` splats:

```python
def _tolerant(cls, data: dict, *, where: str):
    fields = {f.name for f in dataclasses.fields(cls)}
    unknown = data.keys() - fields
    if unknown:
        log.info("ignoring unknown %s fields %s (file newer than reader)", where, sorted(unknown))
    return cls(**{k: v for k, v in data.items() if k in fields})
```

Renaming `value` → `score` would break a 1.0 reader that relied on `value`
(must-ignore cannot rescue it), so that change is a **major** bump (D5).

## Consequences

- **Unblocks ADR 0017.** Under additive-only minors (D5) + tolerant reads (D4),
  the lean typed-payload options (per-phase dataclasses or `TypedDict`) are
  acceptable: typing does not change the JSON shape, and future field additions
  have a defined compatibility story. ADR 0017 can proceed to a decision.
- **Two implementation seams fall out**, each its own work item: (a) write + read
  the `schema_version` stamp, with a version-check on load that distinguishes
  same-major (proceed), older (proceed, D3), and newer (proceed lossy + log, D4);
  (b) the `_tolerant` read seam replacing every `Model(**json)` splat in
  `load_trials` and the event readers, wiring its info logging into ADR 0015's
  structured-logging surface.
- **A new contributor rule:** "schema changes are additive and ride a minor bump;
  removals/renames force a major." This belongs in contributor docs once the
  stamp lands.
- **Readers stop crashing on drift.** The current exact-match-or-`TypeError`
  posture becomes graceful degradation with an audit trail.

## Reconsider Triggers

- The first **major** bump approaches → open the deferred D6 cross-major ADR
  (migration vs. shim vs. unreadable).
- A non-JSONL persistence backend is adopted → the stamp/seam mechanics change.
- Trial directories acquire genuine long-lived/enterprise durability requirements
  (beyond R&D-synthetic) → the `0.x` latitude in D7 and the lossy forward-read in
  D4 warrant revisiting (e.g. fail-closed instead of drop-and-log).
- A dropped-field info log correlates with a real data-loss incident → D4's
  best-effort posture may need to become strict for some files.

## Related

- ADR 0003 (per-trial persistence layout) — the 4-file unit this stamps.
- ADR 0011 (event stream as single source of truth) — why these files are the
  record, not a cache.
- ADR 0013 (driver-run event log) — `run_events.jsonl`, stamped the same way.
- ADR 0015 (structured logging) — home for the D4 ignored-field info logs.
- ADR 0017 (typed event-payload model) — gated on this policy; now unblocked.
- spike S005 (implementation-plan) — the originating spike; resolved here.
- `pi-agent-space-3kz` — the untyped-boundary issue whose remaining half this
  enables.
- `adapters/per_trial_directory_adapter.py` — where the stamp and tolerant seam
  land (`save_trial` / `load_trials`).
