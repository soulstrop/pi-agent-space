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

1. Pre-ADR (question recognized, no draft yet): add a row to the **Open spikes** table at the bottom of [`docs/implementation-plan.md`](../implementation-plan.md) using the next sequential `S###` spike ID. Spike IDs live in their own namespace, separate from ADR numbers, so renumbering one never affects the other. Fill in the question, target phase, and `Status: Open`; leave the **ADR (if opened)** column as `—`.
2. When you draft an ADR for the spike: open the file with `Status: Proposed`, fill in Context and an initial sketch of Options Considered, and add the one-line `Spike in progress; decision target Phase X.Y` note near the top so reviewers know it is still in motion. Update the spike row's **ADR (if opened)** column with the new ADR number. ADRs are numbered by open-date — take the next available number; do not "reserve" ADR numbers in advance.
3. Develop the ADR as the spike progresses: more options surface, prototype findings get folded in, tradeoff notes accumulate.
4. When the spike closes, take one of these paths:
   - **Decision reached** → flip to `Accepted`, fill in Decision / Reconsider Triggers / Consequences, remove the row from the Open spikes table.
   - **Decided against** → flip to `Rejected` with a brief explanation of why; remove the row from the Open spikes table.
   - **Question dissolved** → flip to `Withdrawn`, optionally pointing at a `design-notes.md` entry that captured the residual finding; remove the row from the Open spikes table.

The ADR doubles as the spike's working notebook. There is deliberately no separate spike-notes artifact — write-it-twice has its own cost, and ADR statuses already cover the lifecycle.

## Index of decisions

See the file list in this directory. ADRs are numbered sequentially in the order they were opened (not necessarily the order they were Accepted).
