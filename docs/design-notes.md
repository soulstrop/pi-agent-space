# Design Notes

This document captures **non-obvious design choices** in pi-agent-space — the
kind a future reader might encounter and think *"huh, I wonder why."* It is
deliberately lighter-weight than [ADRs](adrs/), which are reserved for
consequential architectural commitments. Notes here are appendable; each entry
stands alone.

When a note grows in scope, accumulates real consequences, or starts being
referenced in commit messages and design discussions, **promote it to an ADR**.

---

## Format

Each entry uses this skeleton:

```
## {Topic}
**Where:** {file paths or module names}
**Decision:** {one-line statement}

{1–3 paragraphs of context and why}

**Related:** {ADRs, code, tests, memory pointers — optional}
```

New entries go at the bottom of the **Notes** section. Don't reorder existing
entries; the document is an append-only log.

---

## Notes

### Per-trial directory: four files instead of three or two

**Where:** `python/src/pi_evaluator/adapters/per_trial_directory_adapter.py`; ADR 0003.

**Decision:** Each trial directory contains four separate files (`config.json`, `versions.json`, `events.jsonl`, `final.json`), not a consolidated single file or a three-file collapse.

The most defensible candidate consolidation is folding `versions.json` into `config.json` since the version vector is small. We keep them separate because they answer different questions about a trial: `config.json` is *what we proposed*, `versions.json` is *what was actually frozen at trial start*. They diverge whenever the package definition references skills that resolve to different versions over time. Keeping them separate makes the version vector independently greppable across trials without parsing the whole config — which matters once trials accumulate.

The four-file layout is fixed by ADR 0003. Reconsider if (a) per-trial inode pressure becomes real (ADR 0003's >10K trigger), (b) cross-trial queries push us to SQLite, or (c) the version vector grows beyond the small struct it is today.

**Related:** [ADR 0003 — Trial Persistence Strategy](adrs/0003-trial-persistence.md).

---

### ScoringPort: two methods, not one

**Where:** `python/src/pi_evaluator/ports/scoring_port.py`.

**Decision:** `ScoringPort` exposes `score_objective(telemetry) -> Metrics` and `score_subjective(trial) -> SubjectiveScore | None` as separate methods rather than a single unified scoring call.

The two methods mirror Bockeler's computational/inferential split (see `docs/terminology.md` and the math.pdf addendum on user-harness feedback as a lens). Computational scoring is deterministic, fast, and fully observed at trial close — it can run synchronously inside the trial loop. Inferential scoring (LLM judge, human rating) is slow, async, and may never produce a value for a given trial. Collapsing them into one method would force every adapter to either block on subjective scoring or invent a partial-result protocol; the two-method split lets each return its native type.

`score_subjective` takes a full `Trial` (not just a `trial_id`) because subjective scoring may want to inspect the trial's events, configuration, or prior metrics before producing a rating. Passing the trial is more honest about what the contract permits the implementation to look at.

**Related:** `docs/math.pdf` Appendix A; memory `project_inference_vs_computation.md`.

---

### Candidate identity: skills order is significant

**Where:** `python/src/pi_evaluator/domain/identity.py`.

**Decision:** The candidate-identity hash treats `skills` list order as significant; reordering the list produces a different hash.

The package's `skills` represents an ordered pipeline rather than a set: by convention, `["lint", "format", "test"]` and `["test", "format", "lint"]` are semantically distinct because pipeline ordering can change agent behavior at runtime. Order-significance is the conservative default — if two semantically-equivalent reorderings turn out to map to the same effective behavior, that fact emerges as a known-equivalent substitution catalogued by the proposer (Phase 3.2 onward), not as a hash collapse.

Latent concerns that would force revision: (a) if a future ADR ever decides skills should be unordered (a set), the canonicalization changes and any cached hashes become invalid, which would mean a one-time recomputation pass over `trials/`; (b) if international template values ever introduce non-ASCII text, NFC normalization may need to enter the canonical form ahead of `json.dumps`.

**Related:** `python/tests/test_identity.py`; memory `project_inference_vs_computation.md` (substitution principle).
