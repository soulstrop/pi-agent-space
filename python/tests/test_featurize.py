"""Unit tests for Phase 6.1: Package → feature vector encoding.

The encoder must be:
  - deterministic: same package always yields the same vector
  - injective: distinct packages yield distinct vectors
  - structured: each slot block is a valid one-hot (exactly one 1.0, rest 0.0)
  - total-dimension correct: d == sum of per-slot cardinalities
"""

from __future__ import annotations

import pytest

from pi_evaluator.domain.featurize import FeatureEncoder
from pi_evaluator.domain.slot_space import NamedValue, SlotSpace
from pi_evaluator.domain.types import Package


def _space_2x2x2x2() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="flash", value="google/gemini-2.5-flash"),
            NamedValue(name="haiku", value="anthropic/claude-haiku-4-5"),
        ],
        skills_variants=[
            NamedValue(name="minimal", value=("read", "write")),
            NamedValue(name="full", value=("read", "write", "edit", "bash")),
        ],
        system_prompts=[
            NamedValue(name="v0", value="You are a coding assistant."),
            NamedValue(name="terse", value="Be terse."),
        ],
        template_value_variants=[
            NamedValue(name="default", value={}),
            NamedValue(name="python", value={"language": "python"}),
        ],
    )


def _first_package(space: SlotSpace) -> Package:
    return next(space.iter_packages())


# ---------------------------------------------------------------------------
# Dimension
# ---------------------------------------------------------------------------


def test_feature_dim_equals_sum_of_slot_cardinalities():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    assert enc.feature_dim == 2 + 2 + 2 + 2


def test_encode_returns_vector_of_correct_length():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    p = _first_package(space)
    vec = enc.encode(p)
    assert len(vec) == enc.feature_dim


def test_feature_dim_single_value_per_slot():
    space = SlotSpace(
        models=[NamedValue(name="m", value="google/gemini-2.5-flash")],
        skills_variants=[NamedValue(name="s", value=("read",))],
        system_prompts=[NamedValue(name="p", value="prompt")],
        template_value_variants=[NamedValue(name="t", value={})],
    )
    enc = FeatureEncoder(space)
    assert enc.feature_dim == 4


# ---------------------------------------------------------------------------
# One-hot structure
# ---------------------------------------------------------------------------


def test_each_slot_block_is_one_hot():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    slot_sizes = [2, 2, 2, 2]
    for p in space.iter_packages():
        vec = enc.encode(p)
        offset = 0
        for size in slot_sizes:
            block = vec[offset : offset + size]
            assert sum(block) == pytest.approx(1.0)
            assert sorted(block) == pytest.approx([0.0] * (size - 1) + [1.0])
            offset += size


def test_vector_values_are_zero_or_one():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    for p in space.iter_packages():
        for v in enc.encode(p):
            assert v in (0.0, 1.0)


# ---------------------------------------------------------------------------
# Determinism and injectivity
# ---------------------------------------------------------------------------


def test_encode_is_deterministic():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    p = _first_package(space)
    assert enc.encode(p) == enc.encode(p)


def test_distinct_packages_produce_distinct_vectors():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    vectors = [enc.encode(p) for p in space.iter_packages()]
    unique = {tuple(v) for v in vectors}
    assert len(unique) == space.cartesian_size()


def test_second_encoder_from_same_space_agrees():
    space = _space_2x2x2x2()
    enc1 = FeatureEncoder(space)
    enc2 = FeatureEncoder(space)
    for p in space.iter_packages():
        assert enc1.encode(p) == enc2.encode(p)


# ---------------------------------------------------------------------------
# Correct hot bit position
# ---------------------------------------------------------------------------


def test_first_package_hot_bit_is_index_zero_in_each_slot():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    p = _first_package(space)
    vec = enc.encode(p)
    # First value in each 2-element slot → hot at offset 0 within that block.
    assert vec[0] == 1.0 and vec[1] == 0.0  # models block
    assert vec[2] == 1.0 and vec[3] == 0.0  # skills block
    assert vec[4] == 1.0 and vec[5] == 0.0  # system_prompts block
    assert vec[6] == 1.0 and vec[7] == 0.0  # template_values block


def test_second_model_hot_bit_is_index_one():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    packages = list(space.iter_packages())
    # iter_packages: outer loop is models → first 8 use flash, next 8 use haiku.
    haiku_pkg = packages[space.cartesian_size() // 2]
    vec = enc.encode(haiku_pkg)
    assert vec[0] == 0.0 and vec[1] == 1.0  # models block: haiku is index 1


def test_skills_order_insensitive():
    space = SlotSpace(
        models=[NamedValue(name="m", value="google/gemini-2.5-flash")],
        skills_variants=[
            NamedValue(name="s", value=("read", "bash")),
        ],
        system_prompts=[NamedValue(name="p", value="prompt")],
        template_value_variants=[NamedValue(name="t", value={})],
    )
    enc = FeatureEncoder(space)
    pkg_ab = Package(
        model="google/gemini-2.5-flash",
        skills=["read", "bash"],
        system_prompt="prompt",
        template_values={},
    )
    pkg_ba = Package(
        model="google/gemini-2.5-flash",
        skills=["bash", "read"],
        system_prompt="prompt",
        template_values={},
    )
    assert enc.encode(pkg_ab) == enc.encode(pkg_ba)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_encode_raises_for_unknown_model():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    bad = Package(
        model="openai/gpt-4o",
        skills=["read", "write"],
        system_prompt="You are a coding assistant.",
        template_values={},
    )
    with pytest.raises(ValueError, match="model"):
        enc.encode(bad)


def test_encode_raises_for_unknown_skills_variant():
    space = _space_2x2x2x2()
    enc = FeatureEncoder(space)
    bad = Package(
        model="google/gemini-2.5-flash",
        skills=["grep"],
        system_prompt="You are a coding assistant.",
        template_values={},
    )
    with pytest.raises(ValueError, match="skills"):
        enc.encode(bad)
