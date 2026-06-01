"""Phase 6.2: extract per-axis GP training data from a trial history.

Each Pareto axis gets its own (X, Y, Y_var) tuple so GP heads with
sparse observations (e.g. subjective) do not shrink the other heads.

Noise variance per axis (Y_var):
  mean_tokens, mean_dollars, mean_quality:
    capability_profile.per_metric[...].variance, clamped to MIN_NOISE_VAR.
  scaling_slope: no closed-form variance; fixed to MIN_NOISE_VAR.
  subjective: single-point human estimate; fixed to SUBJECTIVE_NOISE_VAR.

Eligibility: completed and boundary_violation trials whose event stream
contains all three required metrics (ADR 0007 — error_escalated excluded;
boundary_violation included as a cost-cliff signal per ADR 0007 §C2).
Trials whose package is outside the encoder's slot space are skipped
silently (the space may have evolved since the trial ran).
"""

from __future__ import annotations

from collections import defaultdict

from ..domain.capability_profile import capability_profile
from ..domain.featurize import FeatureEncoder
from ..domain.types import Trial

# Exported so callers and tests can reference the canonical axis set.
SURROGATE_AXES: tuple[str, ...] = (
    "mean_tokens",
    "mean_dollars",
    "scaling_slope",
    "mean_quality",
    "subjective",
)

# {axis: (X_rows, Y_values, Y_noise_variances)}
SurrogateTrainingData = dict[
    str, tuple[list[list[float]], list[float], list[float]]
]

# {axis: (posterior_means, posterior_variances)}
SurrogatePredictions = dict[str, tuple[list[float], list[float]]]

MIN_NOISE_VAR: float = 1e-6
SUBJECTIVE_NOISE_VAR: float = 0.01

_REQUIRED_METRICS = ("tokens_consumed", "cost_dollars", "quality_score")


def build_training_data(
    trials: list[Trial],
    encoder: FeatureEncoder,
) -> SurrogateTrainingData:
    """Extract per-axis training data from a list of trials.

    Returns a dict with all SURROGATE_AXES as keys; axes with no
    eligible observations map to three empty lists.
    """
    X: dict[str, list[list[float]]] = defaultdict(list)
    Y: dict[str, list[float]] = defaultdict(list)
    Yvar: dict[str, list[float]] = defaultdict(list)

    for trial in trials:
        if trial.outcome in (None, "error_escalated"):
            continue

        profile = capability_profile(trial)
        if not all(m in profile.per_metric for m in _REQUIRED_METRICS):
            continue

        try:
            x = encoder.encode(trial.package)
        except ValueError:
            continue

        tokens = profile.per_metric["tokens_consumed"]
        dollars = profile.per_metric["cost_dollars"]
        quality = profile.per_metric["quality_score"]

        for axis, y, y_var in [
            ("mean_tokens", tokens.mean, tokens.variance),
            ("mean_dollars", dollars.mean, dollars.variance),
            ("scaling_slope", dollars.scaling_slope, MIN_NOISE_VAR),
            ("mean_quality", quality.mean, quality.variance),
        ]:
            X[axis].append(x)
            Y[axis].append(y)
            Yvar[axis].append(max(y_var, MIN_NOISE_VAR))

        if trial.subjective_score is not None:
            X["subjective"].append(x)
            Y["subjective"].append(trial.subjective_score.score)
            Yvar["subjective"].append(SUBJECTIVE_NOISE_VAR)

    return {
        axis: (X[axis], Y[axis], Yvar[axis])
        for axis in SURROGATE_AXES
    }
