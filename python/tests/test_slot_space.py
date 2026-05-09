from __future__ import annotations

import pytest

from pi_evaluator.domain.bockeler import BockelerTag
from pi_evaluator.domain.slot_space import (
    PI_BUILTIN_TOOLS,
    NamedValue,
    SlotSpace,
)
from pi_evaluator.domain.types import Package


def _baseline_space() -> SlotSpace:
    return SlotSpace(
        models=[
            NamedValue(name="gemini-flash", value="google/gemini-2.5-flash"),
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


def test_cartesian_size_matches_product_of_slot_lengths():
    s = _baseline_space()
    assert s.cartesian_size() == 2 * 2 * 2 * 2


def test_iter_packages_yields_full_cartesian_product():
    s = _baseline_space()
    packages = list(s.iter_packages())
    assert len(packages) == s.cartesian_size()
    # All packages are distinct by candidate-identity (no duplicates).
    seen = set()
    for p in packages:
        key = (
            p.model,
            tuple(sorted(p.skills)),
            p.system_prompt,
            tuple(sorted(p.template_values.items())),
        )
        assert key not in seen
        seen.add(key)


def test_iter_packages_returns_real_package_instances():
    s = _baseline_space()
    p = next(s.iter_packages())
    assert isinstance(p, Package)
    # The first emitted product takes the first value from each slot.
    assert p.model == "google/gemini-2.5-flash"
    assert p.skills == ["read", "write"]
    assert p.system_prompt == "You are a coding assistant."
    assert p.template_values == {}


def test_invalid_skill_name_rejected_at_construction():
    with pytest.raises(ValueError, match="Unknown Pi tool names"):
        SlotSpace(
            models=[NamedValue(name="m", value="google/gemini-2.5-flash")],
            skills_variants=[
                NamedValue(name="bad", value=("read", "not_a_real_tool")),
            ],
            system_prompts=[NamedValue(name="p", value="prompt")],
            template_value_variants=[NamedValue(name="t", value={})],
        )


def test_validation_error_lists_all_unknown_skills():
    with pytest.raises(ValueError) as excinfo:
        SlotSpace(
            models=[NamedValue(name="m", value="google/gemini-2.5-flash")],
            skills_variants=[
                NamedValue(name="bad1", value=("foo", "read")),
                NamedValue(name="bad2", value=("bar", "write")),
            ],
            system_prompts=[NamedValue(name="p", value="prompt")],
            template_value_variants=[NamedValue(name="t", value={})],
        )
    msg = str(excinfo.value)
    assert "bar" in msg
    assert "foo" in msg


def test_all_pi_builtin_tools_pass_validation():
    SlotSpace(
        models=[NamedValue(name="m", value="google/gemini-2.5-flash")],
        skills_variants=[
            NamedValue(name="all", value=tuple(sorted(PI_BUILTIN_TOOLS))),
        ],
        system_prompts=[NamedValue(name="p", value="prompt")],
        template_value_variants=[NamedValue(name="t", value={})],
    )


def test_named_value_carries_optional_bockeler_tag():
    untagged = NamedValue(name="m", value="google/gemini-2.5-flash")
    tagged = NamedValue(
        name="read",
        value="read",
        tag=BockelerTag(role="sensor", item_type="computational"),
    )
    assert untagged.tag is None
    assert tagged.tag is not None
    assert tagged.tag.role == "sensor"
    assert tagged.tag.item_type == "computational"


def test_empty_slot_makes_iteration_empty():
    s = SlotSpace(
        models=[],
        skills_variants=[NamedValue(name="m", value=("read",))],
        system_prompts=[NamedValue(name="p", value="prompt")],
        template_value_variants=[NamedValue(name="t", value={})],
    )
    assert s.cartesian_size() == 0
    assert list(s.iter_packages()) == []
