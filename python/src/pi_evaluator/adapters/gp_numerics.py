"""Shared numerical-stability helpers for the GP surrogate + EHVI acquisition.

Two production-hardening concerns live here so the surrogate and the
acquisition share one implementation (ADR 0018):

* **float64 mandate.** BoTorch GP fits and hypervolume math are markedly
  more stable in double precision, and our ARD kernel evaluates
  lengthscales across one-hot (binary) feature columns where float32
  round-off bites hardest. ``f64`` is the single gate every tensor
  construction passes through, so a stray float32 cannot drift in.
* **Cholesky-jitter backstop.** GPyTorch already adds baseline jitter
  before its Cholesky factorization; ``cholesky_safe`` wraps a GP
  operation in an *escalating* jitter schedule and converts a failure
  that survives even the largest nudge into a clear domain error rather
  than an opaque linear-algebra exception deep in a posterior call.

Torch / gpytorch import lazily inside the helpers so importing this
module stays cheap for callers that never touch the GP.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch

# Escalating diagonal nudges tried when a Cholesky factorization fails.
# The first entry matches GPyTorch's float64 baseline; later entries are
# the explicit backstop that escalates before giving up.
JITTER_SCHEDULE: tuple[float, ...] = (1e-8, 1e-6, 1e-4)


class SurrogateNumericalError(RuntimeError):
    """Raised when a GP operation fails Cholesky even at the largest jitter."""


def f64(data: object) -> torch.Tensor:
    """Construct a float64 tensor — the single dtype gate (ADR 0018)."""
    import torch

    return torch.tensor(data, dtype=torch.float64)


def cholesky_safe[T](operation: Callable[[], T], *, what: str) -> T:
    """Run a GP operation, escalating Cholesky jitter on a PSD/linalg failure.

    Tries ``operation`` under each jitter in ``JITTER_SCHEDULE`` in turn,
    returning the first success. If every nudge still yields a non-PSD or
    linear-algebra error, raises ``SurrogateNumericalError`` naming the
    operation (``what``) and chaining the underlying cause.
    """
    import gpytorch
    import torch
    from linear_operator.utils.errors import NotPSDError

    last: Exception | None = None
    for jitter in JITTER_SCHEDULE:
        try:
            # double_value: we run GPs in float64 (see f64).
            with gpytorch.settings.cholesky_jitter(double_value=jitter):
                return operation()
        except (NotPSDError, torch.linalg.LinAlgError) as exc:
            last = exc
    raise SurrogateNumericalError(
        f"{what}: Cholesky factorization failed even at jitter="
        f"{JITTER_SCHEDULE[-1]:g}"
    ) from last
