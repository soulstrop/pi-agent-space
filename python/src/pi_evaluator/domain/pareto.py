"""Pareto frontier over trial metrics (Phase 3.3).

The frontier is computed in 3D — ``(tokens_consumed, cost_dollars,
quality_score)`` — per ADR 0005's commitment to keep tokens and
dollars as independent axes (token-cheap models can be dollar-
expensive across providers, and the operator's limiting factor
varies by deployment).

Dominance: trial ``A`` dominates trial ``B`` when ``A`` is at-least-
as-good on all three axes and strictly better on at least one. Cost
axes (tokens, dollars) are minimized; quality is maximized.

Outcome handling per ADR 0007:
* ``completed`` and ``boundary_violation`` trials are eligible — both
  carry metrics. Boundary violations sit naturally on the cost-cliff
  side of the frontier, which is the signal Phase 6's surrogate
  should see.
* ``error_escalated`` trials and unfinalized trials (``final_metrics
  is None``) are excluded.

Phase 4.4 lifts this to 4D once the ``scaling_slope`` axis from the
capability profile lands. Phase 5 extends to 5D with subjective.
"""

from __future__ import annotations

from .types import Metrics, Trial


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
    if not _has_metrics(new_trial):
        return frontier

    # Optimization: if the new trial is dominated by any existing frontier
    # member, the entire frontier remains unchanged.
    if any(_dominates(f, new_trial) for f in frontier):
        return frontier

    # Otherwise, keep only members that are NOT dominated by the new trial,
    # and add the new trial.
    new_frontier = [f for f in frontier if not _dominates(new_trial, f)]
    new_frontier.append(new_trial)
    return new_frontier


def _has_metrics(trial: Trial) -> bool:
    if trial.final_metrics is None:
        return False
    if trial.outcome == "error_escalated":
        return False
    return True


def _dominates(a: Trial, b: Trial) -> bool:
    """``a`` dominates ``b`` iff a is no worse on every axis and strictly
    better on at least one."""
    if a is b:
        return False
    ma, mb = a.final_metrics, b.final_metrics
    if ma is None or mb is None:
        return False
    return _metrics_dominate(ma, mb)


def _metrics_dominate(a: Metrics, b: Metrics) -> bool:
    no_worse = (
        a.tokens_consumed <= b.tokens_consumed
        and a.cost_dollars <= b.cost_dollars
        and a.quality_score >= b.quality_score
    )
    strictly_better = (
        a.tokens_consumed < b.tokens_consumed
        or a.cost_dollars < b.cost_dollars
        or a.quality_score > b.quality_score
    )
    return no_worse and strictly_better
