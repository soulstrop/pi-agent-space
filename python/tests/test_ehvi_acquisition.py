"""Tests for Phase 6.3 EHVIAcquisition.

Skips if botorch is not importable.  All tests use small n_mc_samples
(32) to keep the suite fast (~100ms per test).
"""

from __future__ import annotations

from typing import Any

import pytest

botorch = pytest.importorskip("botorch")

import torch  # noqa: E402

from pi_evaluator.adapters.ehvi_acquisition import EHVIAcquisition  # noqa: E402
from pi_evaluator.adapters.het_gp_surrogate import HetGPSurrogate  # noqa: E402
from pi_evaluator.domain.surrogate_data import SurrogateTrainingData  # noqa: E402
from pi_evaluator.ports.acquisition_port import AcquisitionFunctionPort  # noqa: E402

_D = 4  # feature dimension for all tests
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
    torch.manual_seed(seed)
    X = torch.rand(n, d).tolist()
    all_axes = axes or [
        "mean_tokens",
        "mean_dollars",
        "scaling_slope",
        "mean_quality",
        "subjective",
    ]
    return {
        ax: (list(X), [float(i) / n for i in range(n)], [1e-4] * n) for ax in all_axes
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
        axes=[
            "mean_tokens",
            "mean_dollars",
            "scaling_slope",
            "mean_quality",
            "subjective",
        ],
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
        axes=[
            "mean_tokens",
            "mean_dollars",
            "scaling_slope",
            "mean_quality",
            "subjective",
        ],
    )
    assert len(scores) == n


def test_scores_are_finite():
    acq = _acq()
    scores = acq.score_candidates(
        X_candidates=_candidates(5),
        pareto_Y=[[0.3] * 5],
        ref_point=[0.0] * 5,
        axes=[
            "mean_tokens",
            "mean_dollars",
            "scaling_slope",
            "mean_quality",
            "subjective",
        ],
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
        axes=[
            "mean_tokens",
            "mean_dollars",
            "scaling_slope",
            "mean_quality",
            "subjective",
        ],
    )
    assert scores == [0.0] * 4


def test_axes_subset_scores_correctly():
    """Scoring over a 2-axis subset of the fitted surrogate works."""
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


def test_cheaper_candidate_ranks_higher_on_cost_axes():
    """2D EHVI over two minimised cost axes (mean_tokens, mean_dollars).
    GPs trained on monotone data y=x; frontier at (0.5, 0.5), ref at the
    high-cost end (1.0, 1.0).  Since both axes are minimised, the cheaper
    candidate (lower posterior means) must rank above the costlier one —
    this exercises the SURROGATE_AXIS_DIRECTIONS orientation."""
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
    # x=0.1 → posterior means ≈ (0.1, 0.1) — cheaper than frontier (0.5, 0.5)
    # x=0.9 → posterior means ≈ (0.9, 0.9) — costlier on both axes
    scores = acq.score_candidates(
        X_candidates=[[0.9], [0.1]],
        pareto_Y=[[0.5, 0.5]],
        ref_point=[1.0, 1.0],  # raw anti-ideal: high cost
        axes=["mean_tokens", "mean_dollars"],
    )
    assert scores[1] > scores[0], (
        f"Expected cheaper x=0.1 to outrank costlier x=0.9, got {scores}"
    )


def test_higher_quality_candidate_ranks_higher():
    """2D EHVI over two maximised axes (mean_quality, subjective).  The
    higher-scoring candidate should rank above the lower one — the mirror
    of the cost-axis test, confirming +1 directions."""
    n = 10
    X = [[float(i) / (n - 1)] for i in range(n)]
    Y = [float(i) / (n - 1) for i in range(n)]
    Y_var = [1e-6] * n

    s = HetGPSurrogate(n_bootstrap=3)
    training: SurrogateTrainingData = {
        "mean_quality": (X, Y, Y_var),
        "subjective": (X, Y, Y_var),
        **{a: ([], [], []) for a in ["mean_tokens", "mean_dollars", "scaling_slope"]},
    }
    s.fit(training)

    acq = EHVIAcquisition(s, n_mc_samples=_N_MC, seed=7)
    scores = acq.score_candidates(
        X_candidates=[[0.9], [0.1]],
        pareto_Y=[[0.5, 0.5]],
        ref_point=[0.0, 0.0],  # raw anti-ideal: low quality
        axes=["mean_quality", "subjective"],
    )
    assert scores[0] > scores[1], (
        f"Expected higher-quality x=0.9 to outrank x=0.1, got {scores}"
    )


def test_agrees_with_botorch_reference():
    """score_candidates uses qLogEHVI with a WeightedMCMultiOutputObjective
    internally — verify output matches a direct qLogEHVI call that applies
    the same -1/+1 orientation to the objective, ref_point, and frontier."""
    from botorch.acquisition.multi_objective.logei import (
        qLogExpectedHypervolumeImprovement,
    )
    from botorch.acquisition.multi_objective.objective import (
        WeightedMCMultiOutputObjective,
    )
    from botorch.models.model_list_gp_regression import ModelListGP
    from botorch.sampling.normal import SobolQMCNormalSampler
    from botorch.utils.multi_objective.hypervolume import FastNondominatedPartitioning

    from pi_evaluator.domain.surrogate_data import SURROGATE_AXIS_DIRECTIONS

    s = _fitted_surrogate(
        n_train=10, axes=["mean_tokens", "mean_dollars"], n_bootstrap=3
    )
    acq = EHVIAcquisition(s, n_mc_samples=_N_MC, seed=99)

    X_cands = _candidates(5)
    axes = ["mean_tokens", "mean_dollars"]
    pareto_Y = [[0.3, 0.3]]
    ref_point = [1.0, 1.0]

    our_scores = acq.score_candidates(X_cands, pareto_Y, ref_point, axes)

    # Reproduce manually, applying the same orientation weights.
    fitted_axes = [ax for ax in axes if ax in s.models]
    joint = ModelListGP(*[s.models[ax] for ax in fitted_axes])
    weights = torch.tensor(
        [SURROGATE_AXIS_DIRECTIONS[ax] for ax in fitted_axes], dtype=torch.float64
    )
    objective = WeightedMCMultiOutputObjective(weights=weights)
    ref_obj = weights * torch.tensor(ref_point, dtype=torch.float64)
    Y_obj = weights * torch.tensor(pareto_Y, dtype=torch.float64)
    # Any: FastNondominatedPartitioning is structurally compatible with
    # the NondominatedPartitioning annotation on qLogEHVI but is not a
    # formal subclass — use Any to avoid a false ty diagnostic.
    partitioning: Any = FastNondominatedPartitioning(ref_point=ref_obj, Y=Y_obj)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([_N_MC]), seed=99)
    ref_acq = qLogExpectedHypervolumeImprovement(
        model=joint,
        ref_point=ref_obj.tolist(),
        partitioning=partitioning,
        sampler=sampler,
        objective=objective,
    )
    X_t = torch.tensor(X_cands, dtype=torch.float64).unsqueeze(1)
    with torch.no_grad():
        ref_scores = ref_acq(X_t).tolist()

    for our, ref in zip(our_scores, ref_scores):
        assert abs(our - ref) < 1e-9, f"Mismatch: {our} vs {ref}"
