"""Phase 6.4 proposer: surrogate-directed package selection.

Composes the GP surrogate (Phase 6.2) and the EHVI acquisition function
(Phase 6.3): on each ``propose`` call it refits the surrogate on the
current history, builds the Pareto frontier, and returns the unseen
slot-space package that maximises EHVI.

Bootstrap discipline lives in the injected surrogate: below its
``n_bootstrap`` threshold no axis fits, ``surrogate.is_fitted`` is False,
and the proposer delegates to a fallback proposer (Phase 3's
``RandomFromSlotSpace``).  The same delegation covers the degenerate
cases where there is no frontier yet or the acquisition is flat.

Acquisition runs over the four always-present objective axes
(``mean_tokens``, ``mean_dollars``, ``scaling_slope``, ``mean_quality``);
the sparse ``subjective`` axis is excluded from the frontier in v1 (see
docs/design-notes.md). Orientation (minimise vs maximise) is handled
inside the acquisition via ``SURROGATE_AXIS_DIRECTIONS``, so the frontier
and reference point are passed in raw metric units.
"""

from __future__ import annotations

from ..domain.candidate_selection import unseen_packages
from ..domain.capability_profile import capability_profile
from ..domain.featurize import FeatureEncoder
from ..domain.pareto import pareto_frontier
from ..domain.slot_space import SlotSpace
from ..domain.surrogate_data import SURROGATE_AXIS_DIRECTIONS, build_training_data
from ..domain.types import EvalSuiteRef, Package, Trial, VersionVector
from ..ports.acquisition_port import AcquisitionFunctionPort
from ..ports.package_proposer_port import PackageProposerPort
from ..ports.surrogate_model_port import SurrogateModelPort

# Dense objective axes EHVI ranks over (subjective excluded in v1).
_ACQ_AXES: list[str] = ["mean_tokens", "mean_dollars", "scaling_slope", "mean_quality"]

# Relative padding so the anti-ideal reference point is strictly dominated
# by every frontier member (avoids zero-hypervolume on a singleton frontier).
_REF_MARGIN = 0.05


class SurrogateProposer(PackageProposerPort):
    """EHVI-directed proposer with random fallback below the bootstrap."""

    def __init__(
        self,
        surrogate: SurrogateModelPort,
        acquisition: AcquisitionFunctionPort,
        encoder: FeatureEncoder,
        slot_space: SlotSpace,
        eval_suite_ref: EvalSuiteRef,
        version_vector: VersionVector,
        fallback: PackageProposerPort,
    ) -> None:
        self._surrogate = surrogate
        self._acquisition = acquisition
        self._encoder = encoder
        self._slot_space = slot_space
        self._eval_suite_ref = eval_suite_ref
        self._version_vector = version_vector
        self._fallback = fallback

    def propose(self, history: list[Trial]) -> Package | None:
        self._surrogate.fit(build_training_data(history, self._encoder))
        if not self._surrogate.is_fitted:
            return self._fallback.propose(history)

        unseen = unseen_packages(
            self._slot_space, history, self._eval_suite_ref, self._version_vector
        )
        if not unseen:
            return None

        frontier = pareto_frontier(history)
        if not frontier:
            return self._fallback.propose(history)
        pareto_Y = [self._objective_axes(t) for t in frontier]

        ref_point = self._ref_point(pareto_Y)
        X = [self._encoder.encode(p) for p in unseen]
        scores = self._acquisition.score_candidates(X, pareto_Y, ref_point, _ACQ_AXES)
        if not any(scores):
            # Flat acquisition (e.g. no usable frontier) — explore randomly.
            return self._fallback.propose(history)

        return max(zip(unseen, scores), key=lambda ps: ps[1])[0]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _objective_axes(self, trial: Trial) -> list[float]:
        """Project a frontier trial onto the 4 dense objective axes (raw units).

        Frontier trials are guaranteed eligible by ``pareto_frontier`` (it
        only admits trials carrying all required metrics), so the metric
        lookups below never miss.
        """
        profile = capability_profile(trial)
        tokens = profile.per_metric["tokens_consumed"]
        dollars = profile.per_metric["cost_dollars"]
        quality = profile.per_metric["quality_score"]
        return [tokens.mean, dollars.mean, dollars.scaling_slope, quality.mean]

    def _ref_point(self, pareto_Y: list[list[float]]) -> list[float]:
        """Anti-ideal point (raw units): worst value per axis, padded.

        Minimised axes (direction < 0) take the column max plus a margin;
        maximised axes take the column min minus a margin.  The acquisition
        applies the orientation signs.
        """
        ref: list[float] = []
        for axis, col in zip(_ACQ_AXES, zip(*pareto_Y), strict=True):
            lo, hi = min(col), max(col)
            span = hi - lo
            margin = (span if span > 0 else max(abs(hi), 1.0)) * _REF_MARGIN
            if SURROGATE_AXIS_DIRECTIONS[axis] < 0:
                ref.append(hi + margin)
            else:
                ref.append(lo - margin)
        return ref
