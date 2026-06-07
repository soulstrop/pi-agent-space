"""Tests for Phase 6.4 SurrogateProposer.

These tests use a mock surrogate and a fake acquisition so they exercise
the proposer's control flow (fit → bootstrap guard → frontier → argmax →
fallback) without pulling in torch/botorch.  A separate botorch-gated
integration test wires the real HetGPSurrogate + EHVIAcquisition.
"""

from __future__ import annotations

import random
from dataclasses import asdict

import pytest
from builders import make_eval_suite_ref, make_version_vector

from pi_evaluator.adapters.random_from_slot_space import RandomFromSlotSpace
from pi_evaluator.adapters.surrogate_proposer import SurrogateProposer
from pi_evaluator.domain.featurize import FeatureEncoder
from pi_evaluator.domain.identity import candidate_identity
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.types import (
    Metrics,
    Outcome,
    Package,
    Trial,
    TrialEvent,
)
from pi_evaluator.ports.package_proposer_port import PackageProposerPort

_REF = make_eval_suite_ref(suite_id="s", suite_version="v")
_VV = make_version_vector(
    pi_version="0.74.0", package_versions={}, eval_suite_version="v"
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
            NamedValue(name="sonnet", value="anthropic/claude-sonnet-4-6"),
        ],
        skills_variants=[NamedValue(name="minimal", value=("read",))],
        system_prompts=[NamedValue(name="v0", value="prompt")],
        template_value_variants=[NamedValue(name="default", value={})],
    )


def _encoder(space: SlotSpace) -> FeatureEncoder:
    return FeatureEncoder(space)


def _metric_events(tokens: int, dollars: float, quality: float) -> list[TrialEvent]:
    ts = "t"
    return [
        TrialEvent(
            phase="eval", timestamp=ts, payload={"problem_id": "p1", "difficulty": 1}
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": "p1",
                "metric_name": "tokens_consumed",
                "value": tokens,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": "p1",
                "metric_name": "cost_dollars",
                "value": dollars,
                "n_samples": 1,
            },
        ),
        TrialEvent(
            phase="metric_record",
            timestamp=ts,
            payload={
                "problem_id": "p1",
                "metric_name": "quality_score",
                "value": quality,
                "n_samples": 1,
            },
        ),
    ]


def _trial(
    model: str,
    *,
    tokens: int = 100,
    dollars: float = 0.01,
    quality: float = 0.8,
    outcome: Outcome = "completed",
    trial_id: str = "t",
) -> Trial:
    return Trial(
        trial_id=trial_id,
        package=Package(
            model=model, system_prompt="prompt", skills=["read"], template_values={}
        ),
        eval_suite_ref=_REF,
        version_vector=_VV,
        events=_metric_events(tokens, dollars, quality)
        if outcome != "error_escalated"
        else [],
        final_metrics=Metrics(
            tokens_consumed=tokens,
            cost_dollars=dollars,
            validation_pass_rate=quality,
            quality_score=quality,
        ),
        outcome=outcome,
    )


# ── test doubles ──────────────────────────────────────────────────────────────


class MockSurrogate:
    """Minimal SurrogateModelPort: fit is a no-op, is_fitted is fixed."""

    def __init__(self, fitted: bool) -> None:
        self._fitted = fitted
        self.fit_calls: list = []

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def fit(self, training_data) -> None:
        self.fit_calls.append(training_data)

    def predict(self, X_query):  # pragma: no cover - not used by proposer
        raise NotImplementedError


class FakeAcquisition:
    """Scores candidates by exact feature-vector match to a target.

    The candidate whose encoded vector equals `target_vec` scores 1.0;
    all others score 0.0, making the argmax deterministic and testable.
    """

    def __init__(self, target_vec: list[float]) -> None:
        self.target_vec = target_vec
        self.calls: list = []

    def score_candidates(self, X_candidates, pareto_Y, ref_point, axes):
        self.calls.append((X_candidates, pareto_Y, ref_point, axes))
        return [1.0 if x == self.target_vec else 0.0 for x in X_candidates]


class ZeroAcquisition:
    """Always returns zeros — simulates a degenerate acquisition."""

    def score_candidates(self, X_candidates, pareto_Y, ref_point, axes):
        return [0.0] * len(X_candidates)


def _fallback(space: SlotSpace, seed: int = 0) -> RandomFromSlotSpace:
    return RandomFromSlotSpace(space, _REF, _VV, rng=random.Random(seed))


def _proposer(
    space: SlotSpace,
    surrogate,
    acquisition,
    *,
    fallback: PackageProposerPort | None = None,
) -> SurrogateProposer:
    return SurrogateProposer(
        surrogate=surrogate,
        acquisition=acquisition,
        encoder=_encoder(space),
        slot_space=space,
        eval_suite_ref=_REF,
        version_vector=_VV,
        fallback=fallback if fallback is not None else _fallback(space),
    )


def _identity(package: Package) -> str:
    return candidate_identity(asdict(package), asdict(_REF), asdict(_VV))


# ── protocol conformance ──────────────────────────────────────────────────────


def test_satisfies_proposer_port():
    space = _space()
    p = _proposer(space, MockSurrogate(fitted=False), ZeroAcquisition())
    assert isinstance(p, PackageProposerPort)


# ── bootstrap fallback ────────────────────────────────────────────────────────


def test_below_bootstrap_delegates_to_fallback():
    """Unfitted surrogate → delegate to the random fallback, which returns
    a valid in-space package."""
    space = _space()
    surrogate = MockSurrogate(fitted=False)
    p = _proposer(space, surrogate, ZeroAcquisition())
    pkg = p.propose([])
    assert pkg is not None
    assert pkg.model in {m.value for m in space.models}
    # surrogate.fit was attempted before the guard
    assert len(surrogate.fit_calls) == 1


def test_empty_frontier_delegates_to_fallback():
    """Fitted surrogate but no eligible trials (all error_escalated) →
    empty frontier → fallback."""
    space = _space()
    history = [
        _trial("google/gemini-2.5-flash", outcome="error_escalated", trial_id="e1")
    ]
    p = _proposer(space, MockSurrogate(fitted=True), ZeroAcquisition())
    pkg = p.propose(history)
    assert pkg is not None  # fallback produced a package


def test_degenerate_scores_delegate_to_fallback():
    """Fitted surrogate, real frontier, but acquisition returns all zeros →
    fallback rather than an arbitrary argmax."""
    space = _space()
    history = [_trial("google/gemini-2.5-flash", trial_id="t1")]
    p = _proposer(space, MockSurrogate(fitted=True), ZeroAcquisition())
    pkg = p.propose(history)
    assert pkg is not None


# ── argmax above bootstrap ────────────────────────────────────────────────────


def test_returns_acquisition_argmax():
    """Fitted surrogate + frontier → proposer returns the unseen candidate
    whose feature vector the acquisition scored highest."""
    space = _space()
    enc = _encoder(space)
    # Target: the sonnet package (unseen); flash is already in history.
    target_pkg = Package(
        model="anthropic/claude-sonnet-4-6",
        system_prompt="prompt",
        skills=["read"],
        template_values={},
    )
    target_vec = enc.encode(target_pkg)

    history = [_trial("google/gemini-2.5-flash", trial_id="t1")]
    p = _proposer(space, MockSurrogate(fitted=True), FakeAcquisition(target_vec))
    pkg = p.propose(history)
    assert pkg == target_pkg


def test_argmax_only_among_unseen():
    """A high-scoring candidate already in history must not be re-proposed;
    the proposer scores only unseen packages."""
    space = _space()
    enc = _encoder(space)
    seen_pkg = Package(
        model="google/gemini-2.5-flash",
        system_prompt="prompt",
        skills=["read"],
        template_values={},
    )
    seen_vec = enc.encode(seen_pkg)
    history = [_trial("google/gemini-2.5-flash", trial_id="t1")]

    # Acquisition would love the seen package, but it must be excluded.
    p = _proposer(space, MockSurrogate(fitted=True), FakeAcquisition(seen_vec))
    pkg = p.propose(history)
    # seen_vec matches nothing unseen → all unseen score 0 → fallback,
    # but whatever is returned must not be the already-seen package.
    assert pkg is not None
    assert _identity(pkg) != _identity(seen_pkg)


def test_passes_four_objective_axes_to_acquisition():
    """The acquisition receives exactly the 4 dense objective axes (no
    subjective) in canonical order."""
    space = _space()
    history = [_trial("google/gemini-2.5-flash", trial_id="t1")]
    acq = FakeAcquisition(target_vec=[])  # matches nothing; we inspect calls
    p = _proposer(space, MockSurrogate(fitted=True), acq)
    p.propose(history)
    assert acq.calls, "acquisition should have been called"
    _, pareto_Y, ref_point, axes = acq.calls[0]
    assert axes == ["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality"]
    assert all(len(row) == 4 for row in pareto_Y)
    assert len(ref_point) == 4


# ── exhaustion ────────────────────────────────────────────────────────────────


def test_exhausted_returns_none():
    """When history covers every package in the slot space, propose → None."""
    space = _space()
    history = [
        _trial("google/gemini-2.5-flash", trial_id="t1"),
        _trial("anthropic/claude-haiku-4-5", trial_id="t2"),
        _trial("anthropic/claude-sonnet-4-6", trial_id="t3"),
    ]
    p = _proposer(space, MockSurrogate(fitted=True), FakeAcquisition(target_vec=[0.0]))
    assert p.propose(history) is None


# ── reference-point derivation ────────────────────────────────────────────────


def test_ref_point_is_strictly_worse_than_frontier():
    """The derived anti-ideal ref point must be dominated by every frontier
    member: above the max on minimised axes, below the min on maximised."""
    space = _space()
    history = [
        _trial(
            "google/gemini-2.5-flash",
            tokens=100,
            dollars=0.01,
            quality=0.9,
            trial_id="t1",
        ),
        _trial(
            "anthropic/claude-haiku-4-5",
            tokens=300,
            dollars=0.05,
            quality=0.6,
            trial_id="t2",
        ),
    ]
    acq = FakeAcquisition(target_vec=[])
    p = _proposer(space, MockSurrogate(fitted=True), acq)
    p.propose(history)
    _, pareto_Y, ref_point, axes = acq.calls[0]
    # axes: tokens(min), dollars(min), slope(min), quality(max)
    cols = list(zip(*pareto_Y))
    assert ref_point[0] > max(cols[0])  # tokens: worse = higher
    assert ref_point[1] > max(cols[1])  # dollars: worse = higher
    assert ref_point[3] < min(cols[3])  # quality: worse = lower


# ── integration with real surrogate + EHVI ────────────────────────────────────


def test_integration_real_surrogate_and_ehvi():
    pytest.importorskip("botorch")
    from pi_evaluator.adapters.ehvi_acquisition import EHVIAcquisition
    from pi_evaluator.adapters.het_gp_surrogate import HetGPSurrogate

    space = _space()
    surrogate = HetGPSurrogate(n_bootstrap=3)
    acquisition = EHVIAcquisition(surrogate, n_mc_samples=32, seed=1)
    p = SurrogateProposer(
        surrogate=surrogate,
        acquisition=acquisition,
        encoder=_encoder(space),
        slot_space=space,
        eval_suite_ref=_REF,
        version_vector=_VV,
        fallback=_fallback(space),
    )
    # 4 eligible trials over 2 of the 3 models (≥ n_bootstrap=3) so the GP fits.
    history = [
        _trial(
            "google/gemini-2.5-flash",
            tokens=100,
            dollars=0.01,
            quality=0.9,
            trial_id="t1",
        ),
        _trial(
            "google/gemini-2.5-flash",
            tokens=120,
            dollars=0.012,
            quality=0.88,
            trial_id="t2",
        ),
        _trial(
            "anthropic/claude-haiku-4-5",
            tokens=300,
            dollars=0.05,
            quality=0.6,
            trial_id="t3",
        ),
        _trial(
            "anthropic/claude-haiku-4-5",
            tokens=280,
            dollars=0.048,
            quality=0.62,
            trial_id="t4",
        ),
    ]
    pkg = p.propose(history)
    assert pkg is not None
    assert pkg.model in {m.value for m in space.models}
    assert surrogate.is_fitted  # the GP actually fit
