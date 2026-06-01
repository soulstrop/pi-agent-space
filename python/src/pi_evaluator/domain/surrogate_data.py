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
    result: SurrogateTrainingData = {axis: ([], [], []) for axis in SURROGATE_AXES}

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

        _append(result, "mean_tokens", x, tokens.mean, tokens.variance)
        _append(result, "mean_dollars", x, dollars.mean, dollars.variance)
        _append(result, "scaling_slope", x, dollars.scaling_slope, MIN_NOISE_VAR)
        _append(result, "mean_quality", x, quality.mean, quality.variance)

        if trial.subjective_score is not None:
            _append(
                result, "subjective",
                x, trial.subjective_score.score, SUBJECTIVE_NOISE_VAR,
            )

    return result


def _append(
    result: SurrogateTrainingData,
    axis: str,
    x: list[float],
    y: float,
    y_var: float,
) -> None:
    xs, ys, yvs = result[axis]
    xs.append(x)
    ys.append(y)
    yvs.append(max(y_var, MIN_NOISE_VAR))
