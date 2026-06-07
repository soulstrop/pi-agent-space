"""Slot/value space schema per Phase 3.1.

A ``SlotSpace`` declares the dimensions the optimizer can vary —
``model``, ``skills``, ``system_prompt``, ``template_values`` — and
the candidate values for each. The proposer (Phase 3.2) picks one
value per slot to construct a ``Package``; the Cartesian product of
slot values is the search space.

Each slot value is a ``NamedValue``: a stable identifier, the actual
value, and an optional Bockeler tag (Phase 6 substitution catalog).
The name is the handle that Phase 6 will use to recognize equivalent
values across slots; it is also useful for human-legible trial
configs and frontier reports.

Skills variants are validated at construction: every individual tool
name within a variant must be in ``PI_BUILTIN_TOOLS`` so a proposed
package can actually run against Pi. Pi extension-installed tools
are out of scope for v1; if needed, expand the validation set when
the extension surface is wired in.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .bockeler import BockelerTag
from .types import Package

PI_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {"read", "bash", "edit", "write", "grep", "find", "ls"}
)
"""Pi 0.74 built-in tool names. The skills slot's individual values
must come from this set."""


@dataclass(frozen=True)
class NamedValue[T]:
    """A slot value with a stable name and optional Bockeler tag.

    The tag is absent by default and absent on slots where the
    Bockeler classification does not apply (e.g., ``model`` — the
    model layer sits below the user harness).
    """

    name: str
    value: T
    tag: BockelerTag | None = None


@dataclass(frozen=True)
class SlotSpace:
    """The optimizer's declared slot/value search space.

    ``skills_variants`` values are tuples to keep them hashable; the
    enumeration converts to ``list[str]`` when constructing
    ``Package`` instances.
    """

    models: list[NamedValue[str]]
    skills_variants: list[NamedValue[tuple[str, ...]]]
    system_prompts: list[NamedValue[str]]
    template_value_variants: list[NamedValue[Mapping[str, str]]]

    def __post_init__(self) -> None:
        invalid = sorted(
            {
                tool
                for variant in self.skills_variants
                for tool in variant.value
                if tool not in PI_BUILTIN_TOOLS
            }
        )
        if invalid:
            raise ValueError(
                f"Unknown Pi tool names in skills_variants: {invalid}. "
                f"Built-ins: {sorted(PI_BUILTIN_TOOLS)}"
            )

    def cartesian_size(self) -> int:
        return (
            len(self.models)
            * len(self.skills_variants)
            * len(self.system_prompts)
            * len(self.template_value_variants)
        )

    def iter_packages(self) -> Iterator[Package]:
        # itertools.product yields tuples in the same order as the equivalent
        # nested loops (leftmost slot varies slowest), so the enumeration order
        # — relied on by the proposer and tests — is unchanged.
        for m, sk, sp, tv in itertools.product(
            self.models,
            self.skills_variants,
            self.system_prompts,
            self.template_value_variants,
        ):
            yield Package(
                model=m.value,
                skills=list(sk.value),
                system_prompt=sp.value,
                template_values=dict(tv.value),
            )
