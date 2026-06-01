"""AcquisitionFunctionPort: typed Protocol for Phase 6.3 EHVI acquisition.

ADR 0016: acquisition operates over the fitted GP heads (one per Pareto
axis) and scores candidate feature vectors by Expected Hypervolume
Improvement against the current non-dominated frontier.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AcquisitionFunctionPort(Protocol):
    """Acquisition function that scores candidate feature vectors."""

    def score_candidates(
        self,
        X_candidates: list[list[float]],
        pareto_Y: list[list[float]],
        ref_point: list[float],
        axes: list[str],
    ) -> list[float]:
        """Return one EHVI score per candidate.

        Parameters
        ----------
        X_candidates:
            Feature vectors to score, shape [n_candidates, feature_dim].
        pareto_Y:
            Current Pareto-optimal objective values, shape
            [n_frontier, len(axes)].  Empty list means no frontier yet.
        ref_point:
            Anti-ideal point, shape [len(axes)].  Candidates that do not
            improve the hypervolume beyond this point receive score ~0.
        axes:
            Ordered list of objective-axis names corresponding to the
            columns of pareto_Y and ref_point.
        """
        ...
