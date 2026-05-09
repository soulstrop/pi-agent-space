"""Phase 3.2 v1 proposer: uniform random over the declared slot space.

Strategy: enumerate the full Cartesian product of the slot space,
filter out packages whose candidate-identity already appears in
history, and pick uniformly from what remains. When history covers
every package, ``propose`` returns ``None``.

Enumerate-and-filter is bounded — for Phase 3's ~100-package slot
spaces, it's cheap and admits no infinite-loop risk. Phase 6's
surrogate proposer replaces this with an acquisition-function-driven
sampler (or pure exploration below ADR 0006's bootstrap threshold).
"""

from __future__ import annotations

import random
from dataclasses import asdict

from ..domain.identity import candidate_identity
from ..domain.slot_space import SlotSpace
from ..domain.types import EvalSuiteRef, Package, Trial, VersionVector
from ..ports.package_proposer_port import PackageProposerPort


class RandomFromSlotSpace(PackageProposerPort):
    """Uniform-random proposer over a slot space, deduped by history.

    ``eval_suite_ref`` and ``version_vector`` are fixed for the
    optimization run — the proposer scopes candidate-identity to its
    own ref/version, matching how the driver will tag the trials it
    produces.
    """

    def __init__(
        self,
        slot_space: SlotSpace,
        eval_suite_ref: EvalSuiteRef,
        version_vector: VersionVector,
        rng: random.Random | None = None,
    ) -> None:
        self._slot_space = slot_space
        self._eval_suite_ref = eval_suite_ref
        self._version_vector = version_vector
        self._rng = rng if rng is not None else random.Random()

    def propose(self, history: list[Trial]) -> Package | None:
        seen = {
            candidate_identity(
                asdict(t.package),
                asdict(t.eval_suite_ref),
                asdict(t.version_vector),
            )
            for t in history
        }
        unseen = [
            p
            for p in self._slot_space.iter_packages()
            if self._identity_for(p) not in seen
        ]
        if not unseen:
            return None
        return self._rng.choice(unseen)

    def _identity_for(self, package: Package) -> str:
        return candidate_identity(
            asdict(package),
            asdict(self._eval_suite_ref),
            asdict(self._version_vector),
        )
