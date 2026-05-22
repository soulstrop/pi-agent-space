"""Adapter that loads graduated problems from a directory tree.

Expected layout::

    {base_dir}/
      001_problem_id/
        problem.json   # GraduatedProblem fields
        ...workspace files...
      002_problem_id/
        problem.json
        ...

When ``problem_ids`` is supplied, ``load()`` returns only the matching
problems. Acceptance tests that want stable real-Pi behavior as the
suite grows (Phase 4.1 adds 002+) should pin to a fixed allowlist
rather than iterating the whole suite.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from ..domain.test_suite import GraduatedProblem
from ..ports.eval_suite_source_port import EvalSuiteSourcePort


class GraduatedProblemSetAdapter(EvalSuiteSourcePort):
    def __init__(
        self,
        base_dir: str | Path,
        problem_ids: Iterable[str] | None = None,
    ) -> None:
        self._base = Path(base_dir)
        self._allowlist: frozenset[str] | None = (
            frozenset(problem_ids) if problem_ids is not None else None
        )

    def load(self) -> list[GraduatedProblem]:
        problems: list[GraduatedProblem] = []
        if not self._base.exists():
            return problems
        for problem_dir in sorted(self._base.iterdir()):
            if not problem_dir.is_dir():
                continue
            problem_file = problem_dir / "problem.json"
            if not problem_file.exists():
                continue
            data = json.loads(problem_file.read_text())
            data["workspace_dir"] = str(problem_dir.resolve())
            problem = GraduatedProblem.from_dict(data)
            if self._allowlist is not None and problem.id not in self._allowlist:
                continue
            problems.append(problem)
        return problems
