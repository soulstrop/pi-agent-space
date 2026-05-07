# Architecture Decision Records (ADRs)

This directory contains ADRs documenting significant technical decisions.

## Status lifecycle

ADRs move through a small set of statuses:

- **Proposed** — drafted; either ready for review or **actively spiking**. When the ADR is being used as a spike notebook (open question still being explored), the Decision and Reconsider Triggers sections may read `TBD` until the spike closes. A one-line note near the top of the ADR — e.g., `Spike in progress; decision target Phase 3.4` — disambiguates "review ready" from "still exploring."
- **Accepted** — decision committed; downstream code and plan steps can rely on it.
- **Rejected** — option considered and explicitly declined; the ADR stays in the directory as a breadcrumb explaining what we are *not* doing.
- **Superseded by ADR XXXX** — replaced by a later decision; both ADRs stay.
- **Withdrawn** — the question dissolved (no longer applicable, or downgraded to a `docs/design-notes.md` entry that captures the finding). A withdrawn ADR points at its replacement when one exists.

## Spike workflow

When an architectural question surfaces that needs exploration before a decision can be made:

1. Open a draft ADR with `Status: Proposed`. Fill in Context and an initial sketch of Options Considered. Add the one-line `Spike in progress; decision target Phase X.Y` note near the top so reviewers know the ADR is still in motion.
2. Add an entry to the **Open spikes** table at the bottom of [`docs/implementation-plan.md`](../implementation-plan.md) — ADR number, the question, the phase it blocks, a status hint.
3. Develop the ADR as the spike progresses: more options surface, prototype findings get folded in, tradeoff notes accumulate.
4. When the spike closes, take one of these paths:
   - **Decision reached** → flip to `Accepted`, fill in Decision / Reconsider Triggers / Consequences, remove the entry from the Open spikes table.
   - **Decided against** → flip to `Rejected` with a brief explanation of why; remove from the Open spikes table.
   - **Question dissolved** → flip to `Withdrawn`, optionally pointing at a `design-notes.md` entry that captured the residual finding.

The ADR doubles as the spike's working notebook. There is deliberately no separate spike-notes artifact — write-it-twice has its own cost, and ADR statuses already cover the lifecycle.

## Index of decisions

See the file list in this directory. ADRs are numbered sequentially in the order they were opened (not necessarily the order they were Accepted).
