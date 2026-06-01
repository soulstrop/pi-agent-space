"""SurrogateModelPort: typed Protocol for the Phase 6 GP surrogate.

ADR 0016: fixed-observed-noise SingleTaskGP (BoTorch), 5 independent
heads, bootstrap guard in the proposer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.surrogate_data import SurrogatePredictions, SurrogateTrainingData


@runtime_checkable
class SurrogateModelPort(Protocol):
    """Gaussian-process surrogate over Package feature vectors."""

    @property
    def is_fitted(self) -> bool: ...

    def fit(self, training_data: SurrogateTrainingData) -> None: ...

    def predict(self, X_query: list[list[float]]) -> SurrogatePredictions: ...
