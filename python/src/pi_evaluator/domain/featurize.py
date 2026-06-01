"""Phase 6.1: Package → fixed-length one-hot feature vector.

``FeatureEncoder`` maps a ``Package`` to a float vector φ(x) ∈ ℝ^d
where d = Σ|slot| across the four SlotSpace dimensions.  Each slot
contributes a one-hot block; blocks are concatenated in a stable,
schema-defined order: models, skills_variants, system_prompts,
template_value_variants.

The encoding is:
  - deterministic: order follows the SlotSpace list order, not Python
    dict/set iteration order.
  - injective: distinct packages within the space map to distinct vectors.
  - order-insensitive for skills: skills are matched by frozenset so
    Package(skills=["read","bash"]) == Package(skills=["bash","read"]).
"""

from __future__ import annotations

from dataclasses import dataclass

from .slot_space import SlotSpace
from .types import Package


@dataclass(frozen=True)
class FeatureEncoder:
    """Encodes a ``Package`` as a one-hot feature vector against a fixed ``SlotSpace``.

    Build once per optimization run and reuse; the encoder holds index
    maps derived from the slot lists at construction time.
    """

    _slot_space: SlotSpace
    _model_index: dict[str, int]
    _skills_index: dict[frozenset[str], int]
    _prompt_index: dict[str, int]
    _template_index: dict[frozenset[tuple[str, str]], int]
    feature_dim: int

    def __init__(self, slot_space: SlotSpace) -> None:
        object.__setattr__(self, "_slot_space", slot_space)
        object.__setattr__(
            self,
            "_model_index",
            {nv.value: i for i, nv in enumerate(slot_space.models)},
        )
        object.__setattr__(
            self,
            "_skills_index",
            {frozenset(nv.value): i for i, nv in enumerate(slot_space.skills_variants)},
        )
        object.__setattr__(
            self,
            "_prompt_index",
            {nv.value: i for i, nv in enumerate(slot_space.system_prompts)},
        )
        object.__setattr__(
            self,
            "_template_index",
            {
                frozenset(nv.value.items()): i
                for i, nv in enumerate(slot_space.template_value_variants)
            },
        )
        dim = (
            len(slot_space.models)
            + len(slot_space.skills_variants)
            + len(slot_space.system_prompts)
            + len(slot_space.template_value_variants)
        )
        object.__setattr__(self, "feature_dim", dim)

    def encode(self, package: Package) -> list[float]:
        """Return the one-hot feature vector for *package*.

        Raises ``ValueError`` if any package field is not found in the
        corresponding slot list.
        """
        vec: list[float] = [0.0] * self.feature_dim
        offset = 0

        model_idx = self._model_index.get(package.model)
        if model_idx is None:
            raise ValueError(
                f"model {package.model!r} not in slot space "
                f"(known: {list(self._model_index)})"
            )
        vec[offset + model_idx] = 1.0
        offset += len(self._slot_space.models)

        skills_key = frozenset(package.skills)
        skills_idx = self._skills_index.get(skills_key)
        if skills_idx is None:
            raise ValueError(
                f"skills {sorted(package.skills)} not in slot space "
                f"(known: {[sorted(k) for k in self._skills_index]})"
            )
        vec[offset + skills_idx] = 1.0
        offset += len(self._slot_space.skills_variants)

        prompt_idx = self._prompt_index.get(package.system_prompt)
        if prompt_idx is None:
            raise ValueError(
                f"system_prompt not in slot space "
                f"(first 40 chars: {package.system_prompt[:40]!r})"
            )
        vec[offset + prompt_idx] = 1.0
        offset += len(self._slot_space.system_prompts)

        template_key = frozenset(package.template_values.items())
        template_idx = self._template_index.get(template_key)
        if template_idx is None:
            raise ValueError(
                f"template_values {dict(package.template_values)} not in slot space"
            )
        vec[offset + template_idx] = 1.0

        return vec
