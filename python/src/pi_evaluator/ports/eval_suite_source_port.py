"""EvalSuiteSourcePort: load a graduated problem set from disk."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.test_suite import GraduatedProblem


@runtime_checkable
class EvalSuiteSourcePort(Protocol):
    """Load problems for a trial. Once loaded, the suite is just data."""

    def load(self) -> list[GraduatedProblem]: ...
