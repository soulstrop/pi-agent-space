from __future__ import annotations

import random

from pi_evaluator.adapters.random_from_slot_space import RandomFromSlotSpace
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Package,
    Trial,
    VersionVector,
)
from pi_evaluator.ports.package_proposer_port import PackageProposerPort


def _suite_ref() -> EvalSuiteRef:
    return EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0")


def _versions() -> VersionVector:
    return VersionVector(
        pi_version="0.74.0", package_versions={}, eval_suite_version="0.1.0"
    )


def _slot_space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
        ],
        skills_variants=[
            NamedValue(name="minimal", value=("read", "write")),
            NamedValue(name="full", value=("read", "write", "edit", "bash")),
        ],
        system_prompts=[
            NamedValue(name="v0", value="You are a coding assistant."),
        ],
        template_value_variants=[
            NamedValue(name="default", value={}),
        ],
    )  # cartesian: 2 * 2 * 1 * 1 = 4


def _trial(package: Package, trial_id: str = "t") -> Trial:
    return Trial(
        trial_id=trial_id,
        package=package,
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        outcome="completed",
    )


def _package_key(p: Package) -> tuple:
    return (
        p.model,
        p.system_prompt,
        tuple(sorted(p.skills)),
        tuple(sorted(p.template_values.items())),
    )


def _proposer(seed: int = 0) -> RandomFromSlotSpace:
    return RandomFromSlotSpace(
        slot_space=_slot_space(),
        eval_suite_ref=_suite_ref(),
        version_vector=_versions(),
        rng=random.Random(seed),
    )


def test_satisfies_port_protocol():
    assert isinstance(_proposer(), PackageProposerPort)


def test_proposes_package_from_slot_space_when_history_empty():
    proposer = _proposer()
    package = proposer.propose([])
    assert package is not None
    assert package in list(_slot_space().iter_packages())


def test_skips_already_evaluated_configurations():
    space = _slot_space()
    all_packages = list(space.iter_packages())
    history = [_trial(p, trial_id=f"t{i}") for i, p in enumerate(all_packages[:3])]
    proposer = _proposer()
    package = proposer.propose(history)
    assert package is not None
    assert package == all_packages[3]  # only one left


def test_returns_none_when_space_exhausted():
    space = _slot_space()
    history = [
        _trial(p, trial_id=f"t{i}") for i, p in enumerate(space.iter_packages())
    ]
    assert _proposer().propose(history) is None


def test_seeded_rng_makes_proposer_deterministic():
    a = _proposer(seed=42).propose([])
    b = _proposer(seed=42).propose([])
    assert a == b


def test_proposer_distribution_covers_full_space_eventually():
    """Repeatedly proposing without history (no dedup carry-over between
    calls) eventually yields each package at least once."""
    proposer = _proposer(seed=0)
    seen: set[tuple] = set()
    for _ in range(200):
        p = proposer.propose([])
        assert p is not None
        seen.add(_package_key(p))
    expected = {_package_key(p) for p in _slot_space().iter_packages()}
    assert seen == expected


def test_history_with_different_eval_suite_does_not_dedup():
    """A trial against a different eval suite has a different candidate
    identity, so it should not block re-proposing the same package
    against this proposer's eval suite."""
    space = _slot_space()
    first = next(space.iter_packages())
    other_suite = EvalSuiteRef(suite_id="other", suite_version="0.1.0")
    foreign_trial = Trial(
        trial_id="foreign",
        package=first,
        eval_suite_ref=other_suite,
        version_vector=_versions(),
        outcome="completed",
    )
    proposer = _proposer()
    # Across many proposals, ``first`` should still be reachable — it has not
    # been evaluated against this proposer's eval suite.
    candidates: set[tuple] = set()
    for _ in range(50):
        p = proposer.propose([foreign_trial])
        assert p is not None
        candidates.add(_package_key(p))
    assert _package_key(first) in candidates
