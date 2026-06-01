"""History-aware candidate selection over a slot space.

Both proposers (``RandomFromSlotSpace`` and ``SurrogateProposer``) need
the same primitive: the slot-space packages not yet covered by history,
deduplicated by candidate identity.  This is the single home for that
logic so the subtle parts stay consistent — notably that the *seen* set
is keyed by each trial's own ``eval_suite_ref`` / ``version_vector``
while the candidate check uses the proposer's fixed ref/version, and
that ``candidate_identity`` canonicalizes skill ordering.
"""

from __future__ import annotations

from dataclasses import asdict

from .identity import candidate_identity
from .slot_space import SlotSpace
from .types import EvalSuiteRef, Package, Trial, VersionVector


def unseen_packages(
    slot_space: SlotSpace,
    history: list[Trial],
    eval_suite_ref: EvalSuiteRef,
    version_vector: VersionVector,
) -> list[Package]:
    """Return slot-space packages whose candidate identity is not in history.

    ``eval_suite_ref`` / ``version_vector`` scope the identity of the
    *candidate* packages to the current run; each historical trial is
    keyed by its own ref/version.
    """
    seen = {
        candidate_identity(
            asdict(t.package), asdict(t.eval_suite_ref), asdict(t.version_vector)
        )
        for t in history
    }
    ref = asdict(eval_suite_ref)
    versions = asdict(version_vector)
    return [
        p
        for p in slot_space.iter_packages()
        if candidate_identity(asdict(p), ref, versions) not in seen
    ]
