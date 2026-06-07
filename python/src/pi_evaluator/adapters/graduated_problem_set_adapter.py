"""Adapter that loads graduated problems from a directory tree.

Expected layout::

    {base_dir}/
      001_problem_id/
        problem.json   # GraduatedProblem fields
        ...workspace files...
      002_problem_id/
        problem.json
        ...

``problem_ids`` semantics:

- ``None`` (default) — no filter; every well-formed problem is loaded.
- An iterable of strings — allowlist matched against each problem's JSON
  ``id`` field (NOT the directory name; they may differ per the example
  above). Problems whose ``id`` is not in the allowlist are skipped
  *before* schema validation, so malformed-but-excluded ``problem.json``
  files do not abort the load — this is what makes pinned acceptance
  tests stable as the suite grows.
- An empty iterable — allowlist matches nothing; ``load()`` returns ``[]``.
  Use ``None`` if you mean "no filter."
- A bare ``str`` is rejected with ``TypeError`` (Python footgun: ``str``
  is itself ``Iterable[str]`` of characters, so passing one would
  silently empty the load). Wrap single ids in a list.

A ``problem.json`` that is not valid JSON is skipped with a logged warning
rather than aborting the load; a parseable-but-schema-incomplete problem
still raises (the safety net), unless excluded by the allowlist.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from ..domain.test_suite import GraduatedProblem
from ..ports.eval_suite_source_port import EvalSuiteSourcePort

logger = logging.getLogger(__name__)


class GraduatedProblemSetAdapter(EvalSuiteSourcePort):
    def __init__(
        self,
        base_dir: str | Path,
        problem_ids: Iterable[str] | None = None,
    ) -> None:
        self._base = Path(base_dir)
        if isinstance(problem_ids, str):
            raise TypeError(
                "problem_ids must be an iterable of strings, not a bare str "
                f"(got {problem_ids!r}); wrap a single id in a list."
            )
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
            try:
                data = json.loads(problem_file.read_text())
            except json.JSONDecodeError as exc:
                logger.warning(
                    "skipping problem with malformed JSON",
                    extra={
                        "event": "problem_json_malformed",
                        "problem_dir": problem_dir.name,
                        "error": str(exc),
                    },
                )
                continue
            if self._allowlist is not None and data.get("id") not in self._allowlist:
                continue
            data["workspace_dir"] = str(problem_dir.resolve())
            problems.append(GraduatedProblem.from_dict(data))
        return problems
