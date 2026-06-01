"""Tests for the shared GP numerical-stability helpers (ADR 0018).

Skips if botorch/torch is not importable.  The Cholesky-failure paths are
exercised with injected errors rather than a real singular kernel —
GPyTorch's built-in jitter usually absorbs genuine near-singular cases,
so we test the escalation/give-up logic directly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from linear_operator.utils.errors import NotPSDError  # noqa: E402

from pi_evaluator.adapters.gp_numerics import (  # noqa: E402
    JITTER_SCHEDULE,
    SurrogateNumericalError,
    cholesky_safe,
    f64,
)


def test_f64_casts_to_double():
    t = f64([[0.0, 1.0], [1.0, 0.0]])
    assert t.dtype == torch.float64


def test_cholesky_safe_returns_value_on_success():
    assert cholesky_safe(lambda: 42, what="noop") == 42


def test_cholesky_safe_retries_then_succeeds():
    """Fails NotPSDError on the first jitter, succeeds on the second."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise NotPSDError("matrix not PSD")
        return "ok"

    assert cholesky_safe(flaky, what="flaky") == "ok"
    assert calls["n"] == 2


def test_cholesky_safe_gives_up_after_full_schedule():
    """Persistent failure across every jitter raises SurrogateNumericalError."""
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise torch.linalg.LinAlgError("cholesky failed")

    with pytest.raises(SurrogateNumericalError, match="what-label"):
        cholesky_safe(always_fail, what="what-label")
    assert calls["n"] == len(JITTER_SCHEDULE)


def test_cholesky_safe_chains_underlying_cause():
    err = NotPSDError("root cause")

    def boom():
        raise err

    with pytest.raises(SurrogateNumericalError) as exc_info:
        cholesky_safe(boom, what="op")
    assert exc_info.value.__cause__ is err
