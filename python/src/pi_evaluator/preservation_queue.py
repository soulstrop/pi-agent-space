"""Derived view over PersistencePort for ADR 0007 B1's preservation queue.

When a trial's retry budget exhausts, ``classify_outcome`` tags it
``error_escalated`` and ``finalize_trial`` writes that outcome into
``final.json``. The trial directory (workspace + telemetry + stderr)
is already on disk through the normal trial lifecycle — *preservation*
is automatic.

The *queue* surface is a derived filter, not a separately written
artifact: ``preserved_error_trials`` scans ``PersistencePort.load_trials``
and returns the subset with ``outcome == "error_escalated"``. See the
"Persistent-error preservation queue: derive-don't-store v1" note in
``docs/design-notes.md`` for the rationale, and ADR 0011 for the
broader "outcome is the single source of truth" discipline this
inherits.
"""

from __future__ import annotations

from .domain.types import Trial
from .ports.persistence_port import PersistencePort


def preserved_error_trials(persistence: PersistencePort) -> list[Trial]:
    """Return all trials whose final outcome is ``error_escalated``.

    Trials still open (no ``final.json``) and trials closed as
    ``completed`` or ``boundary_violation`` are excluded. Ordering
    follows whatever ``persistence.load_trials()`` returns
    (``PerTrialDirectoryAdapter`` returns trial-id-sorted).
    """
    return [t for t in persistence.load_trials() if t.outcome == "error_escalated"]
