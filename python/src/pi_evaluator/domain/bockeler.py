"""Bockeler 2x2 classification of user-harness items.

Per project memory ``project_inference_vs_computation``: each item in
the user harness is tagged on a 2x2 of ``(role, item_type)`` where
role ∈ {guide, sensor} and item_type ∈ {computational, inferential}.
A swap from inferential to computational of the same role is strictly
Pareto-dominant, so the Phase 6 surrogate can exploit a known-
equivalent substitution catalog ahead of any random move.

Phase 3.1 declares the tag structure on slot values; Phase 6 uses it
operationally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["guide", "sensor"]
ItemType = Literal["computational", "inferential"]


@dataclass(frozen=True)
class BockelerTag:
    role: Role
    item_type: ItemType
