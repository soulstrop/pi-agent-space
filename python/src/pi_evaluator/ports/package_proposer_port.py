"""PackageProposerPort: produce the next package to evaluate.

The proposer is the optimization brain: Phase 3 uses
``RandomFromSlotSpace`` (uniform random over the declared search
space with history-aware dedup); Phase 6 replaces it with a
surrogate-driven proposer (HetGP + EHVI / pure exploration below
the bootstrap threshold per ADR 0006).

``propose(history)`` returns ``None`` when the proposer is exhausted
— for Phase 3, when every package in the slot space has already been
evaluated. The driver treats ``None`` as a graceful stop signal.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.types import Package, Trial


@runtime_checkable
class PackageProposerPort(Protocol):
    def propose(self, history: list[Trial]) -> Package | None: ...
