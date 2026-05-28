"""Pareto frontier over trial capability profiles (Phase 4.4 / ADR 0012).

The frontier is computed in 4D — ``(mean_tokens, mean_dollars,
scaling_slope_of_cost_dollars, mean_quality)`` — per ADR 0005's commitment
to keep tokens and dollars as independent axes and ADR 0012's slope axis
on cost_dollars (the dollar-cliff signal is what an unattended optimizer
needs to see).

Per ADR 0012's consequences: tokens-slope is also computed (it lives in
the capability profile for diagnostics) but is not a Pareto axis in v1.
The operator-facing harm is the dollar cliff, not the token cliff.

Dominance: trial ``A`` dominates trial ``B`` when ``A`` is at-least-as-
good on all four axes and strictly better on at least one. Cost axes
(``mean_tokens``, ``mean_dollars``, ``scaling_slope``) are minimized;
quality is maximized.

Outcome handling per ADR 0007:

* ``completed`` and ``boundary_violation`` trials are eligible — both
  carry metric_record events. Boundary violations sit naturally on the
  cost-cliff side of the frontier, which is the signal Phase 6's
  surrogate should see.
* ``error_escalated`` trials and trials missing any required axis
  (``tokens_consumed``, ``cost_dollars``, ``quality_score``) are
  excluded.

Phase 5 extends to 5D with subjective scoring.
"""

from __future__ import annotations

from .capability_profile import CapabilityProfile, capability_profile
from .types import Trial

_REQUIRED_AXES = ("tokens_consumed", "cost_dollars", "quality_score")


def pareto_frontier(trials: list[Trial]) -> list[Trial]:
    frontier: list[Trial] = []
    for t in trials:
        frontier = add_to_frontier(frontier, t)
    return frontier


def add_to_frontier(frontier: list[Trial], new_trial: Trial) -> list[Trial]:
    """Incrementally update the Pareto frontier with a new trial.

    Returns a new frontier list containing ``new_trial`` if it is non-
    dominated, and removing any existing members it dominates.
    """
    new_axes = _pareto_axes(new_trial)
    if new_axes is None:
        return frontier

    frontier_axes = [(t, _pareto_axes(t)) for t in frontier]
    if any(
        axes is not None and _axes_dominate(axes, new_axes)
        for _, axes in frontier_axes
    ):
        return frontier

    survivors = [
        t
        for t, axes in frontier_axes
        if axes is None or not _axes_dominate(new_axes, axes)
    ]
    survivors.append(new_trial)
    return survivors


def _pareto_axes(trial: Trial) -> tuple[float, float, float, float] | None:
    """Project a trial onto the 4D Pareto coordinate.

    Returns ``None`` when the trial is ineligible: an error_escalated
    outcome, or a profile missing one of the required axes.
    """
    if trial.outcome == "error_escalated":
        return None
    profile = capability_profile(trial)
    if not _has_required_axes(profile):
        return None
    tokens = profile.per_metric["tokens_consumed"]
    dollars = profile.per_metric["cost_dollars"]
    quality = profile.per_metric["quality_score"]
    return (tokens.mean, dollars.mean, dollars.scaling_slope, quality.mean)


def _has_required_axes(profile: CapabilityProfile) -> bool:
    return all(axis in profile.per_metric for axis in _REQUIRED_AXES)


def _axes_dominate(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    a_tokens, a_dollars, a_slope, a_quality = a
    b_tokens, b_dollars, b_slope, b_quality = b
    no_worse = (
        a_tokens <= b_tokens
        and a_dollars <= b_dollars
        and a_slope <= b_slope
        and a_quality >= b_quality
    )
    strictly_better = (
        a_tokens < b_tokens
        or a_dollars < b_dollars
        or a_slope < b_slope
        or a_quality > b_quality
    )
    return no_worse and strictly_better
