"""Phase 6.3: EHVI acquisition function using BoTorch qLogEHVI (ADR 0016).

Wraps the fitted HetGPSurrogate heads in a ModelListGP and scores
candidate feature vectors via qLogExpectedHypervolumeImprovement.

Bootstrap discipline: score_candidates() returns zeros when fewer than
2 requested axes are fitted (an unfitted surrogate has no fitted axes)
or when no Pareto frontier exists yet; the SurrogateProposer (Phase 6.4)
falls back to RandomFromSlotSpace in those cases.

torch / botorch imports are deferred to score_candidates() so that
importing this module does not pull in torch for callers that never
invoke the acquisition function.
"""

from __future__ import annotations

from typing import Any

from .het_gp_surrogate import HetGPSurrogate

N_MC_SAMPLES_DEFAULT: int = 64


class EHVIAcquisition:
    """qLogEHVI acquisition over independent GP heads (one per Pareto axis).

    Parameters
    ----------
    surrogate:
        Fitted HetGPSurrogate.  score_candidates() returns zeros when
        surrogate.is_fitted is False.
    n_mc_samples:
        Number of quasi-Monte Carlo samples (Sobol) per candidate.
        Larger values give more accurate EHVI estimates at higher cost.
    seed:
        Optional seed for the SobolQMCNormalSampler.  Pass an integer
        for reproducible scores; None uses a fresh Sobol sequence.
    """

    def __init__(
        self,
        surrogate: HetGPSurrogate,
        n_mc_samples: int = N_MC_SAMPLES_DEFAULT,
        seed: int | None = None,
    ) -> None:
        self._surrogate = surrogate
        self.n_mc_samples = n_mc_samples
        self.seed = seed

    def score_candidates(
        self,
        X_candidates: list[list[float]],
        pareto_Y: list[list[float]],
        ref_point: list[float],
        axes: list[str],
    ) -> list[float]:
        """Return one qLogEHVI score per candidate.

        Parameters
        ----------
        X_candidates:
            Feature vectors, shape [n_candidates, feature_dim].
        pareto_Y:
            Current Pareto-optimal objective values, shape
            [n_frontier, len(fitted_axes)].  Empty means no frontier.
        ref_point:
            Anti-ideal reference point, shape [len(axes)].  Columns must
            be in the same order as `axes`.
        axes:
            Ordered objective-axis names.  Axes not present in the fitted
            surrogate are silently dropped; pareto_Y and ref_point are
            sliced accordingly.

        Returns
        -------
        list[float]
            qLogEHVI scores in log-space, length n_candidates.  All zeros
            when fewer than 2 requested axes are fitted (qLogEHVI needs
            at least 2 objectives) or no Pareto frontier exists yet — in
            both cases the proposer falls back to random.
        """
        models = self._surrogate.models
        fitted_axes = [ax for ax in axes if ax in models]
        if len(fitted_axes) < 2 or not pareto_Y:
            return [0.0] * len(X_candidates)

        import torch
        from botorch.acquisition.multi_objective.logei import (
            qLogExpectedHypervolumeImprovement,
        )
        from botorch.models.model_list_gp_regression import ModelListGP
        from botorch.sampling.normal import SobolQMCNormalSampler
        from botorch.utils.multi_objective.hypervolume import (
            FastNondominatedPartitioning,
        )

        # Joint model + ref_point/frontier sliced to the fitted axes,
        # preserving the order of `axes`.
        joint = ModelListGP(*[models[ax] for ax in fitted_axes])
        idx = [axes.index(ax) for ax in fitted_axes]
        ref = [ref_point[i] for i in idx]
        Y_t = torch.tensor(
            [[row[i] for i in idx] for row in pareto_Y], dtype=torch.float64
        )

        # Any: FastNondominatedPartitioning is structurally compatible with
        # the NondominatedPartitioning annotation on qLogEHVI but is not a
        # formal subclass — use Any to avoid a false ty diagnostic.
        partitioning: Any = FastNondominatedPartitioning(
            ref_point=torch.tensor(ref, dtype=torch.float64), Y=Y_t
        )
        sampler = SobolQMCNormalSampler(
            sample_shape=torch.Size([self.n_mc_samples]), seed=self.seed
        )
        acq = qLogExpectedHypervolumeImprovement(
            model=joint, ref_point=ref, partitioning=partitioning, sampler=sampler
        )

        # q=1: unsqueeze to [n_candidates, 1, feature_dim]
        X_t = torch.tensor(X_candidates, dtype=torch.float64).unsqueeze(1)
        with torch.no_grad():
            return acq(X_t).tolist()
