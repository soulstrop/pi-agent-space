"""Tests for Phase 6.3 EHVIAcquisition.

Skips if botorch is not importable.  All tests use small n_mc_samples
(32) to keep the suite fast (~100ms per test).
"""

from __future__ import annotations

import pytest

botorch = pytest.importorskip("botorch")

import torch  # noqa: E402

from pi_evaluator.adapters.ehvi_acquisition import EHVIAcquisition  # noqa: E402
from pi_evaluator.adapters.het_gp_surrogate import HetGPSurrogate  # noqa: E402
from pi_evaluator.domain.surrogate_data import SurrogateTrainingData  # noqa: E402
from pi_evaluator.ports.acquisition_port import AcquisitionFunctionPort  # noqa: E402

_D = 4      # feature dimension for all tests
_N_MC = 32  # fast MC for tests


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_surrogate(n_bootstrap: int = 3) -> HetGPSurrogate:
    return HetGPSurrogate(n_bootstrap=n_bootstrap)


def _training_data(
    n: int,
    axes: list[str] | None = None,
    *,
    d: int = _D,
    seed: int = 0,
) -> SurrogateTrainingData:
    """Minimal training data with a clear linear trend for easy GP fitting."""
    rng = torch.manual_seed(seed)
    X = torch.rand(n, d).tolist()
    all_axes = axes or ["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality", "subjective"]
    return {
        ax: (list(X), [float(i) / n for i in range(n)], [1e-4] * n)
        for ax in all_axes
    }


def _fitted_surrogate(
    n_train: int = 8,
    axes: list[str] | None = None,
    n_bootstrap: int = 3,
) -> HetGPSurrogate:
    s = _make_surrogate(n_bootstrap=n_bootstrap)
    s.fit(_training_data(n_train, axes))
    assert s.is_fitted
    return s


def _acq(surrogate: HetGPSurrogate | None = None, n_mc: int = _N_MC) -> EHVIAcquisition:
    if surrogate is None:
        surrogate = _fitted_surrogate()
    return EHVIAcquisition(surrogate, n_mc_samples=n_mc, seed=42)


def _candidates(n: int, d: int = _D) -> list[list[float]]:
    return [[float(i) / max(n - 1, 1)] * d for i in range(n)]


# ── protocol conformance ──────────────────────────────────────────────────────


def test_satisfies_acquisition_port():
    assert isinstance(_acq(), AcquisitionFunctionPort)


# ── bootstrap guard ───────────────────────────────────────────────────────────


def test_returns_zeros_when_surrogate_not_fitted():
    s = _make_surrogate(n_bootstrap=10)
    s.fit(_training_data(n=3))  # below threshold for all axes
    assert not s.is_fitted
    acq = EHVIAcquisition(s, n_mc_samples=_N_MC)
    scores = acq.score_candidates(
        X_candidates=_candidates(5),
        pareto_Y=[],
        ref_point=[0.0] * 5,
        axes=["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality", "subjective"],
    )
    assert scores == [0.0] * 5


def test_returns_zeros_for_axes_not_in_surrogate():
    """axes arg that has zero overlap with fitted surrogate → zeros."""
    s = _fitted_surrogate(axes=["mean_tokens"])
    acq = EHVIAcquisition(s, n_mc_samples=_N_MC)
    scores = acq.score_candidates(
        X_candidates=_candidates(3),
        pareto_Y=[],
        ref_point=[0.0, 0.0],
        axes=["mean_dollars", "mean_quality"],  # not fitted in s
    )
    assert scores == [0.0] * 3


# ── output shape ──────────────────────────────────────────────────────────────


def test_output_length_matches_candidates():
    acq = _acq()
    n = 7
    scores = acq.score_candidates(
        X_candidates=_candidates(n),
        pareto_Y=[],
        ref_point=[0.0] * 5,
        axes=["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality", "subjective"],
    )
    assert len(scores) == n


def test_scores_are_finite():
    acq = _acq()
    scores = acq.score_candidates(
        X_candidates=_candidates(5),
        pareto_Y=[[0.3] * 5],
        ref_point=[0.0] * 5,
        axes=["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality", "subjective"],
    )
    assert all(isinstance(s, float) for s in scores)
    assert all(not (s != s) for s in scores)  # no NaN


# ── behavioral correctness ────────────────────────────────────────────────────


def test_empty_frontier_returns_zeros():
    """FastNondominatedPartitioning requires at least one Pareto point.
    When no frontier exists the proposer will fall back to random sampling;
    score_candidates() signals this by returning zeros."""
    acq = _acq()
    scores = acq.score_candidates(
        X_candidates=_candidates(4),
        pareto_Y=[],
        ref_point=[0.0] * 5,
        axes=["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality", "subjective"],
    )
    assert scores == [0.0] * 4


def test_axes_subset_scores_correctly():
    """Scoring over a 2-axis subset of the fitted surrogate should work without error."""
    s = _fitted_surrogate(axes=["mean_tokens", "mean_dollars", "mean_quality"])
    acq = EHVIAcquisition(s, n_mc_samples=_N_MC, seed=42)
    scores = acq.score_candidates(
        X_candidates=_candidates(4),
        pareto_Y=[[0.4, 0.4]],
        ref_point=[0.0, 0.0],
        axes=["mean_tokens", "mean_dollars"],
    )
    assert len(scores) == 4
    assert all(isinstance(s, float) for s in scores)


def test_better_candidate_ranks_higher_in_2d():
    """2D EHVI: GPs trained on monotone data over both axes, frontier at
    (0.5, 0.5).  The candidate whose posterior means exceed the frontier
    should rank above the one whose means fall below it."""
    n = 10
    X = [[float(i) / (n - 1)] for i in range(n)]
    Y = [float(i) / (n - 1) for i in range(n)]
    Y_var = [1e-6] * n

    s = HetGPSurrogate(n_bootstrap=3)
    training: SurrogateTrainingData = {
        "mean_tokens": (X, Y, Y_var),
        "mean_dollars": (X, Y, Y_var),
        **{a: ([], [], []) for a in ["scaling_slope", "mean_quality", "subjective"]},
    }
    s.fit(training)

    acq = EHVIAcquisition(s, n_mc_samples=_N_MC, seed=7)
    # x=0.9 → posterior means ≈ (0.9, 0.9) — well above frontier (0.5, 0.5)
    # x=0.1 → posterior means ≈ (0.1, 0.1) — below frontier on both axes
    scores = acq.score_candidates(
        X_candidates=[[0.9], [0.1]],
        pareto_Y=[[0.5, 0.5]],
        ref_point=[0.0, 0.0],
        axes=["mean_tokens", "mean_dollars"],
    )
    assert scores[0] > scores[1], f"Expected score(x=0.9) > score(x=0.1), got {scores}"


def test_agrees_with_botorch_reference():
    """score_candidates uses qLogEHVI internally — verify output matches
    a direct qLogEHVI call on the same models and candidates."""
    from botorch.acquisition.multi_objective.logei import (
        qLogExpectedHypervolumeImprovement,
    )
    from botorch.models.model_list_gp_regression import ModelListGP
    from botorch.sampling.normal import SobolQMCNormalSampler
    from botorch.utils.multi_objective.hypervolume import FastNondominatedPartitioning

    s = _fitted_surrogate(n_train=10, axes=["mean_tokens", "mean_dollars"], n_bootstrap=3)
    acq = EHVIAcquisition(s, n_mc_samples=_N_MC, seed=99)

    X_cands = _candidates(5)
    axes = ["mean_tokens", "mean_dollars"]
    pareto_Y = [[0.3, 0.3]]
    ref_point = [0.0, 0.0]

    our_scores = acq.score_candidates(X_cands, pareto_Y, ref_point, axes)

    # Reproduce manually
    fitted_axes = [ax for ax in axes if ax in s._models]
    joint = ModelListGP(*[s._models[ax] for ax in fitted_axes])
    ref_t = torch.tensor(ref_point, dtype=torch.float64)
    Y_t = torch.tensor(pareto_Y, dtype=torch.float64)
    partitioning = FastNondominatedPartitioning(ref_point=ref_t, Y=Y_t)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([_N_MC]), seed=99)
    ref_acq = qLogExpectedHypervolumeImprovement(
        model=joint,
        ref_point=ref_t.tolist(),
        partitioning=partitioning,
        sampler=sampler,
    )
    X_t = torch.tensor(X_cands, dtype=torch.float64).unsqueeze(1)
    with torch.no_grad():
        ref_scores = ref_acq(X_t).tolist()

    for our, ref in zip(our_scores, ref_scores):
        assert abs(our - ref) < 1e-9, f"Mismatch: {our} vs {ref}"
