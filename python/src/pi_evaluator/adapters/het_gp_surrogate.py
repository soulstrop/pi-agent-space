"""Phase 6.2: GP surrogate adapter using BoTorch SingleTaskGP (ADR 0016).

5 independent GP heads — one per Pareto axis.  Each head uses
BoTorch's SingleTaskGP with observed per-input noise (train_Yvar),
a Matern-5/2 ARD kernel, and output standardization.

Bootstrap discipline: an axis is skipped when it has fewer than
n_bootstrap observations.  predict() only returns predictions for
fitted axes.  The SurrogateProposer (Phase 6.4) falls back to
RandomFromSlotSpace when no axes are fitted.

torch / botorch imports are deferred to fit() so that importing this
module does not pull in torch for callers that never invoke the GP.
"""

from __future__ import annotations

from ..domain.surrogate_data import SurrogateTrainingData
from ..ports.surrogate_model_port import SurrogatePredictions

N_BOOTSTRAP_DEFAULT: int = 10


class SurrogateNotFittedError(RuntimeError):
    """Raised when predict() is called before any axis is fitted."""


class HetGPSurrogate:
    """Fixed-observed-noise GP surrogate with one BoTorch head per axis.

    Parameters
    ----------
    n_bootstrap:
        Minimum number of observations required to fit a GP head.
        Axes below this threshold are skipped; the proposer falls back
        to random when no axes meet the threshold.
    """

    def __init__(self, n_bootstrap: int = N_BOOTSTRAP_DEFAULT) -> None:
        self.n_bootstrap = n_bootstrap
        self._models: dict = {}

    @property
    def is_fitted(self) -> bool:
        return bool(self._models)

    @property
    def models(self) -> dict:
        """Read-only view of fitted GP heads keyed by axis name.

        Empty until fit() runs with enough observations.  Consumers
        (e.g. EHVIAcquisition) read this to build a joint model over
        the fitted axes.
        """
        return self._models

    def fit(self, training_data: SurrogateTrainingData) -> None:
        """Fit one GP per axis that has >= n_bootstrap observations.

        Replaces any previously fitted models in full — a refit with
        insufficient data clears the fitted state.
        """
        import torch
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from gpytorch.mlls import ExactMarginalLogLikelihood

        new_models: dict = {}
        for axis, (X, Y, Y_var) in training_data.items():
            if len(X) < self.n_bootstrap:
                continue
            train_X = torch.tensor(X, dtype=torch.float64)
            train_Y = torch.tensor(Y, dtype=torch.float64).unsqueeze(-1)
            train_Yvar = torch.tensor(Y_var, dtype=torch.float64).unsqueeze(-1)
            model = SingleTaskGP(train_X, train_Y, train_Yvar=train_Yvar)
            mll = ExactMarginalLogLikelihood(model.likelihood, model)
            fit_gpytorch_mll(mll)
            model.eval()
            new_models[axis] = model

        self._models = new_models

    def predict(self, X_query: list[list[float]]) -> SurrogatePredictions:
        """Return posterior (mean, variance) per fitted axis.

        Raises SurrogateNotFittedError if no axes have been fitted yet.
        Axes below the bootstrap threshold at fit() time are absent
        from the returned dict.
        """
        if not self.is_fitted:
            raise SurrogateNotFittedError(
                f"No axes fitted — call fit() with >= {self.n_bootstrap} "
                "observations per axis first."
            )
        import torch

        X_t = torch.tensor(X_query, dtype=torch.float64)
        result: SurrogatePredictions = {}
        for axis, model in self._models.items():
            with torch.no_grad():
                posterior = model.posterior(X_t)
                means: list[float] = posterior.mean.squeeze(-1).tolist()
                variances: list[float] = posterior.variance.squeeze(-1).tolist()
            result[axis] = (means, variances)
        return result
