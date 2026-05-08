"""Adapter that loads graduated problems from a directory tree.

Expected layout::

    {base_dir}/
      001_problem_id/
        problem.json   # GraduatedProblem fields
        ...workspace files...
      002_problem_id/
        problem.json
        ...
"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.test_suite import GraduatedProblem
from ..ports.eval_suite_source_port import EvalSuiteSourcePort


class GraduatedProblemSetAdapter(EvalSuiteSourcePort):
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

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
            problems.append(GraduatedProblem.from_dict(data))
        return problems
