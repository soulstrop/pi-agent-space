"""Tests for Phase 6.2 HetGPSurrogate (BoTorch FixedNoiseGP).

Skips if botorch is not importable, so the unit suite remains runnable
without the full torch stack.
"""

from __future__ import annotations

import random

import pytest

botorch = pytest.importorskip("botorch")

from pi_evaluator.adapters.het_gp_surrogate import (  # noqa: E402
    HetGPSurrogate,
    SurrogateNotFittedError,
)
from pi_evaluator.domain.surrogate_data import SURROGATE_AXES  # noqa: E402
from pi_evaluator.ports.surrogate_model_port import (  # noqa: E402
    SurrogateModelPort,
    SurrogateTrainingData,
)

_ALL_AXES = list(SURROGATE_AXES)
_D = 4  # small feature dimension for tests


def _data(
    n: int,
    axes: list[str] | None = None,
    *,
    d: int = _D,
    seed: int = 42,
) -> SurrogateTrainingData:
    rng = random.Random(seed)
    X = [[rng.random() for _ in range(d)] for _ in range(n)]
    return {
        axis: (
            list(X),
            [rng.random() for _ in range(n)],
            [1e-4 + rng.random() * 1e-3 for _ in range(n)],
        )
        for axis in (axes or _ALL_AXES)
    }


def _full_data(n: int, *, seed: int = 42) -> SurrogateTrainingData:
    """All 5 axes populated with n rows."""
    return _data(n, _ALL_AXES, seed=seed)


def _surrogate(n_bootstrap: int = 3) -> HetGPSurrogate:
    return HetGPSurrogate(n_bootstrap=n_bootstrap)


# ── Protocol conformance ──────────────────────────────────────────────────────


def test_het_gp_surrogate_satisfies_protocol():
    assert isinstance(_surrogate(), SurrogateModelPort)


# ── initial state ─────────────────────────────────────────────────────────────


def test_not_fitted_initially():
    assert _surrogate().is_fitted is False


def test_predict_raises_when_not_fitted():
    s = _surrogate()
    with pytest.raises(SurrogateNotFittedError):
        s.predict([[0.0] * _D])


# ── bootstrap guard ───────────────────────────────────────────────────────────


def test_fit_below_bootstrap_leaves_unfitted():
    s = _surrogate(n_bootstrap=5)
    s.fit(_full_data(n=4))
    assert s.is_fitted is False


def test_fit_exactly_at_bootstrap_threshold_sets_fitted():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=3))
    assert s.is_fitted is True


def test_fit_above_bootstrap_threshold_sets_fitted():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=6))
    assert s.is_fitted is True


def test_sparse_axis_not_fitted_below_threshold():
    """Axes below n_bootstrap are omitted from the fitted set while
    axes above the threshold proceed normally."""
    rng = random.Random(7)
    X5 = [[rng.random() for _ in range(_D)] for _ in range(5)]
    X2 = [[rng.random() for _ in range(_D)] for _ in range(2)]
    combined: SurrogateTrainingData = {
        "mean_tokens": (X5, [rng.random() for _ in range(5)], [1e-4] * 5),
        "mean_dollars": (X5, [rng.random() for _ in range(5)], [1e-4] * 5),
        "mean_quality": (X2, [rng.random() for _ in range(2)], [1e-4] * 2),
        "scaling_slope": ([], [], []),
        "subjective": ([], [], []),
    }
    s = _surrogate(n_bootstrap=3)
    s.fit(combined)
    assert s.is_fitted  # two axes have enough data
    rng2 = random.Random(99)
    preds = s.predict([[rng2.random() for _ in range(_D)]])
    assert "mean_tokens" in preds
    assert "mean_dollars" in preds
    assert "mean_quality" not in preds  # below threshold
    assert "scaling_slope" not in preds
    assert "subjective" not in preds


# ── predict output shape ──────────────────────────────────────────────────────


def test_predict_returns_all_fitted_axes():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=5))
    preds = s.predict([[0.5] * _D])
    assert set(preds.keys()) == set(_ALL_AXES)


def test_predict_output_length_matches_query_count():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=5))
    n_query = 7
    preds = s.predict([[0.5] * _D] * n_query)
    for means, variances in preds.values():
        assert len(means) == n_query
        assert len(variances) == n_query


def test_posterior_variances_are_positive():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=5))
    preds = s.predict([[0.0] * _D, [1.0] * _D, [0.5] * _D])
    for means, variances in preds.values():
        assert all(v > 0 for v in variances)


# ── posterior quality ─────────────────────────────────────────────────────────


def test_posterior_mean_interpolates_between_training_points():
    """At training inputs the posterior mean should be close to the
    observed output (within noise level). Uses a 1-feature space."""
    n = 8
    X = [[float(i) / n] for i in range(n)]
    Y = [float(i) / n for i in range(n)]
    Y_var = [1e-6] * n
    s = HetGPSurrogate(n_bootstrap=3)
    training: SurrogateTrainingData = {
        "mean_tokens": (X, Y, Y_var),
        **{a: ([], [], []) for a in _ALL_AXES if a != "mean_tokens"},
    }
    s.fit(training)
    preds = s.predict(X)
    means, _ = preds["mean_tokens"]
    for pred, true in zip(means, Y):
        assert abs(pred - true) < 0.2, f"pred={pred:.3f} true={true:.3f}"


# ── refit ─────────────────────────────────────────────────────────────────────


def test_refit_replaces_previous_model():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=5, seed=1))
    preds_before = s.predict([[0.5] * _D])
    s.fit(_full_data(n=5, seed=2))
    preds_after = s.predict([[0.5] * _D])
    any_different = any(
        abs(preds_before[ax][0][0] - preds_after[ax][0][0]) > 1e-9
        for ax in preds_before
    )
    assert any_different


def test_refit_with_below_threshold_data_clears_fitted_state():
    s = _surrogate(n_bootstrap=3)
    s.fit(_full_data(n=5))
    assert s.is_fitted
    s.fit(_full_data(n=2))  # below threshold for all axes
    assert s.is_fitted is False
