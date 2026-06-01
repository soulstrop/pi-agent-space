"""SurrogateModelPort: typed Protocol for the Phase 6 GP surrogate.

Type aliases live here so both the domain (surrogate_data.py) and the
adapter (het_gp_surrogate.py) import from the same definition.

ADR 0016: fixed-observed-noise SingleTaskGP (BoTorch), 5 independent
heads, bootstrap guard in the proposer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.surrogate_data import SurrogateTrainingData

# {axis_name: (posterior_means, posterior_variances)}
SurrogatePredictions = dict[str, tuple[list[float], list[float]]]


@runtime_checkable
class SurrogateModelPort(Protocol):
    """Gaussian-process surrogate over Package feature vectors."""

    @property
    def is_fitted(self) -> bool: ...

    def fit(self, training_data: SurrogateTrainingData) -> None: ...

    def predict(self, X_query: list[list[float]]) -> SurrogatePredictions: ...
