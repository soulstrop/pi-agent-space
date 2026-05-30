# Title: 0014 - Re-finalize semantics

**Status:** Accepted

## Context

ADR 0007 (Pi Invocation Lifecycle) established that every trial emits a
`finalized` event as the last entry in its `events.jsonl`. `TrialRunner`
enforces this by construction: `finalized` is emitted immediately before
`PersistencePort.finalize_trial(...)` is called. Consumers that need the
trial's final outcome read the `finalized` event's `outcome` field or the
companion `final.json`.

Phase 5 introduces retroactive subjective scoring: after a trial is closed,
a human (or a future automated scorer) supplies a rating via the `pi-eval
score` CLI. The plan's implementation spec calls for two side effects:

1. **Append** a `subjective_score` event to the trial's `events.jsonl`.
2. **Atomically update** `final.json` to include the `SubjectiveScore`
   fields alongside the existing objective metrics.

Side effect (1) directly conflicts with the current invariant: if
`subjective_score` is appended *after* `finalized`, then `finalized` is
no longer the last event. Consumers that infer "trial is done" by checking
whether the last event has `phase == "finalized"` would malfunction.

Side effect (2) alone does not break the invariant; it is the event-stream
append that forces the question.

This spike settles which shape the retroactive update takes so that Phase
5.2 has a stable foundation.

### What consumers currently assume about `finalized`

- `lifecycle.classify_outcome` reads the event stream but determines
  outcome from telemetry classification, not by scanning for `finalized`
  as the last event. It is **not** last-event-sensitive.
- `PerTrialDirectoryAdapter.load_trials` reconstructs `Trial` objects from
  `final.json` (outcome, metrics, subjective_score) plus event replay. It
  does not require `finalized` to be last.
- The `pi-eval score` CLI does not exist yet; its design is downstream of
  this ADR.
- No current consumer breaks if events follow `finalized` — but the
  invariant is in ADR 0007's prose ("every trial finalizes"; the event is
  the terminal marker), and changing it silently invites future drift.

## Options Considered

### F1 — Relax the invariant; `finalized` marks objective closure only

`finalized` is redefined as "the last objective-phase event." Events with
retroactive-amendment semantics (`subjective_score`, and any future phases)
may follow it. The rule becomes:

> *A trial's objective pipeline is complete when its event stream contains
> a `finalized` event. Events after `finalized` are retroactive amendments
> and do not re-open the objective pipeline.*

ADR 0007 is updated with a one-paragraph amendment noting the relaxation.

- **Pros:** Simplest implementation — `pi-eval score` just appends and
  rewrites `final.json`. No new event phase. The canonical event-stream
  shape remains a single linear file.
- **Cons:** Requires any future consumer that uses "last event is
  `finalized`" as a sentinel to be corrected. The relaxation must be
  documented clearly enough that future contributors don't re-introduce
  the assumption. Grep-ability of "is this trial done?" degrades slightly
  (must scan for `finalized`, not just read the last line).

### F2 — Introduce a `re-finalized` event

After appending the `subjective_score` event, the CLI also appends a
`re-finalized` event that closes the amended record. The invariant
strengthens to:

> *A trial is fully closed when its last event is `finalized`
> (no subjective score) or `re-finalized` (subjective score present).*

`re-finalized`'s payload mirrors `finalized`: objective metrics + outcome
+ `subjective_score` fields, so a reader can reconstruct full trial state
from the last event alone.

- **Pros:** Preserves a strong "last event is the terminal marker"
  invariant; each close has a named sentinel. `final.json` and the last
  event are always in sync.
- **Cons:** More events per amended trial; `re-finalized` must be defined
  and tested separately from `finalized`. Consumers that handle `finalized`
  must also handle `re-finalized` (though both can be dispatched by the
  same branch if the payload shape is identical). The extra event adds
  complexity without adding information beyond what `final.json` already
  carries.

### F3 — Subjective score in `final.json` only; `events.jsonl` is immutable after `finalized`

The retroactive update writes only to `final.json` (which already supports
`subjective_score: SubjectiveScore | None`). No event is appended to
`events.jsonl`. The current invariant is unchanged.

```
events.jsonl  ← immutable after finalized; no subjective_score event
final.json    ← atomically updated to include subjective_score
```

Consumers that want to know *when* and *by whom* a trial was scored read
`SubjectiveScore.scorer` and `SubjectiveScore.timestamp` from `final.json`.

- **Pros:** Cleanest separation — `events.jsonl` is a true append-only log
  that closes at `finalized`; `final.json` is the mutable summary. No
  invariant change required. The persistence adapter already supports
  `finalize_trial(..., subjective_score=...)`.
- **Cons:** Breaks the project's "event stream is the SoT" discipline
  (ADR 0011 framing). If `events.jsonl` is replayed, the derived view
  does not include the subjective score; only `final.json` carries it.
  This creates a two-SoT situation that ADR 0012 (CapabilityProfile
  placement option P2) explicitly rejected for the same reason.

### F4 — Separate `subjective.json` sidecar

Subjective score lives in its own file alongside `final.json`:

```
<trial_id>/
  config.json
  versions.json
  events.jsonl    ← immutable after finalized
  final.json      ← objective metrics + outcome
  subjective.json ← subjective_score (absent until scored)
```

- **Pros:** Decouples the two concerns completely; `events.jsonl` stays
  immutable; `final.json` stays objective-only. The presence/absence of
  `subjective.json` is trivially detectable.
- **Cons:** Grows the 4-file layout (ADR 0003) to 5 files, requiring
  updates to all layout documentation, `PersistencePort`, and consumers.
  The score metadata (`scorer`, `timestamp`) is already in `SubjectiveScore`
  — a separate file adds indirection without adding information.

## Decision

**F4 — Separate `subjective.json` sidecar.**

Rationale: inter-rater reliability experiments are anticipated but the
right schema for multiple raters is an open question requiring
experimentation. A dedicated file keeps that design space open without
touching `events.jsonl` or `final.json`. Runs where no subjective rating
is ever given have a clean absence (no file) rather than a null field.

Two sub-decisions are incorporated:

- **`final.json` becomes objective-only.** The `subjective_score` field is
  removed from `final.json` entirely. `final.json` carries objective
  metrics and outcome; `subjective.json` carries the subjective score.
  There is no denormalized copy.
- **Single score per trial for now.** `subjective.json` holds one
  `SubjectiveScore` (score, notes, scorer, timestamp). Multi-rater support
  is deferred; the Reconsider Triggers section captures the extension paths.

The `events.jsonl` invariant from ADR 0007 is **unchanged**: `finalized`
remains the last event in `events.jsonl`, always. No amendment to ADR 0007
is required.

The prototype-finding note in the draft is resolved: the "What consumers
currently assume" section above confirms no existing consumer reads
`trial.events[-1]` as a sentinel, so the invariant preservation is
belt-and-suspenders rather than a required fix.

## Reconsider Triggers

- **Inter-rater reliability lands.** When multiple scorers rate the same
  trial, extend `subjective.json` to an array of `SubjectiveScore` entries
  (additive, backward-compatible) or introduce a `subjective/` subdirectory
  with one file per rater. The `scorer` + `timestamp` fields already
  attribute each score; the aggregation question (mean, majority, weighted)
  is what drives the schema choice.
- **Audit trail for scoring events.** If operators need a machine-readable
  record of *when* each scoring action occurred beyond what
  `SubjectiveScore.timestamp` carries (e.g. who invoked the CLI, from which
  host), add a `scoring_events.jsonl` or route scoring actions through the
  run-level `run_events.jsonl` (ADR 0013).
- **`subjective.json` grows additional fields.** Confidence interval,
  rubric version, annotation rationale — all additive to the existing
  shape; no migration required for existing files.

## Consequences

- The trial directory layout grows from 4 files to 5 when a subjective
  score is present. ADR 0003's layout table is updated to document
  `subjective.json` as an optional fifth file.
- `final.json` drops the `subjective_score` field. `PerTrialDirectoryAdapter
  .finalize_trial()` drops its `subjective_score` parameter; `final.json`
  is now written from objective metrics and outcome only.
- `PersistencePort` gains one new method:
  `write_subjective_score(trial_id: str, ss: SubjectiveScore) -> None`.
  The implementation writes `subjective.json` atomically
  (temp-then-rename per ADR 0003 precedent). In-memory stubs used in
  tests add a no-op implementation.
- `PerTrialDirectoryAdapter.load_trials()` checks for `subjective.json`
  alongside `final.json` when reconstructing `Trial` objects; if present,
  it populates `Trial.subjective_score`; if absent, `Trial.subjective_score`
  stays `None`. This preserves the existing in-memory shape of `Trial`.
- `domain/events.py` — the `subjective_score_event()` helper and its
  12 tests (`test_subjective_score_event.py`) were written during Phase 5.1
  under the assumption that a subjective score event would be appended to
  `events.jsonl`. With F4 there is no such event; both the helper and tests
  should be removed as part of the Phase 5.2 implementation commit. The
  Phase 5.1 deliverable is superseded: the event schema question is resolved
  by the file schema instead.
- The Phase 5 deliverable description in `docs/implementation-plan.md`
  ("appends a subjective-score event") is stale; it should be updated to
  reflect that the `pi-eval score` CLI writes `subjective.json` rather than
  appending to `events.jsonl`.
- `docs/adrs/0003-trial-persistence.md` is amended in a sibling commit to
  document the optional fifth file.
