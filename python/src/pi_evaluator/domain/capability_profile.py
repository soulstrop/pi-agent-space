"""Phase 4.3 / ADR 0012: trial-level capability profile.

A ``CapabilityProfile`` is a derived view over a ``Trial`` — it groups the
trial's ``metric_record`` events by ``metric_name`` and computes per-axis
summary statistics. The profile is not persisted; consumers re-derive on
demand. The aggregator reads only events on the trial (``eval`` events
supply per-problem ``difficulty``, ``metric_record`` events supply
``value`` / ``n_samples``), so ``events.jsonl`` alone is sufficient input.

``scaling_slope`` is the OLS slope of ``value`` vs. ``difficulty`` per
metric (linear). It returns ``0.0`` when fewer than two distinct
difficulty levels appear in the trial — the slope is undefined when the
x-axis has no spread.

``n_samples`` on a ``MetricSummary`` is the count of ``(problem,
replication)`` data points contributing to the summary, not the
per-problem replica count. With v1's no-replication regime (ADR 0006), it
equals the number of distinct problems for the metric.

Per ADR 0011's derive-don't-store discipline, this module reads from
``Trial.events`` only — never from ``Trial.final_metrics``. If the
event stream and ``final_metrics`` ever drift, the event stream is the
single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from .event_payloads import EvalRecord, MetricRecord, parse
from .types import Trial


@dataclass(frozen=True)
class MetricSummary:
    """Per-axis summary statistics across the trial's per-problem records."""

    mean: float
    variance: float
    p95: float
    n_samples: int
    scaling_slope: float


@dataclass(frozen=True)
class CapabilityProfile:
    """Trial-level profile keyed by ``metric_name``."""

    per_metric: dict[str, MetricSummary]


def capability_profile(trial: Trial) -> CapabilityProfile:
    """Derive the capability profile from a trial's event stream."""
    difficulty_by_problem = _difficulty_index(trial)
    points_by_metric: dict[str, list[tuple[int, float]]] = {}
    for event in trial.events:
        record = parse(event)
        if not isinstance(record, MetricRecord):
            continue
        difficulty = difficulty_by_problem.get(record.problem_id, 0)
        points_by_metric.setdefault(record.metric_name, []).append(
            (difficulty, float(record.value))
        )
    return CapabilityProfile(
        per_metric={
            name: _summarize(points) for name, points in points_by_metric.items()
        }
    )


def _difficulty_index(trial: Trial) -> dict[str, int]:
    index: dict[str, int] = {}
    for event in trial.events:
        record = parse(event)
        if isinstance(record, EvalRecord):
            index[record.problem_id] = int(record.difficulty)
    return index


def _summarize(points: list[tuple[int, float]]) -> MetricSummary:
    n = len(points)
    if n == 0:
        return MetricSummary(0.0, 0.0, 0.0, 0, 0.0)
    values = [v for _, v in points]
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return MetricSummary(
        mean=mean,
        variance=variance,
        p95=_p95(values),
        n_samples=n,
        scaling_slope=_scaling_slope(points),
    )


def _p95(values: list[float]) -> float:
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = 0.95 * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (rank - lo) * (sorted_values[hi] - sorted_values[lo])


def _scaling_slope(points: list[tuple[int, float]]) -> float:
    if len(points) < 2 or len({d for d, _ in points}) < 2:
        return 0.0
    n = len(points)
    mean_d = sum(d for d, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    numerator = sum((d - mean_d) * (v - mean_v) for d, v in points)
    denominator = sum((d - mean_d) ** 2 for d, _ in points)
    if denominator == 0:
        return 0.0
    return numerator / denominator
