import json
from pathlib import Path

from pi_evaluator.adapters.graduated_problem_set_adapter import (
    GraduatedProblemSetAdapter,
)
from pi_evaluator.domain.test_suite import GraduatedProblem
from pi_evaluator.ports.eval_suite_source_port import EvalSuiteSourcePort

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"


def test_adapter_satisfies_port_protocol(tmp_path):
    assert isinstance(GraduatedProblemSetAdapter(tmp_path), EvalSuiteSourcePort)


def test_loading_001_binary_search_yields_expected_fields():
    adapter = GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR)
    problems = adapter.load()
    by_id = {p.id: p for p in problems}
    assert "001_binary_search" in by_id
    p = by_id["001_binary_search"]
    assert isinstance(p, GraduatedProblem)
    assert p.title == "Implement Binary Search"
    assert p.difficulty == 1
    assert "binary search" in p.prompt.lower()
    assert p.workspace_dir.endswith("001_binary_search")
    assert any(step.command.startswith("pytest") for step in p.validation_steps)
    assert "python" in p.tags


def test_load_from_empty_directory_returns_empty(tmp_path):
    adapter = GraduatedProblemSetAdapter(tmp_path)
    assert adapter.load() == []


def test_load_from_nonexistent_directory_returns_empty(tmp_path):
    adapter = GraduatedProblemSetAdapter(tmp_path / "does-not-exist")
    assert adapter.load() == []


def test_load_skips_directories_without_problem_json(tmp_path):
    (tmp_path / "incomplete").mkdir()
    (tmp_path / "complete").mkdir()
    (tmp_path / "complete" / "problem.json").write_text(
        json.dumps(
            {
                "id": "complete",
                "title": "Complete",
                "difficulty": 2,
                "prompt": "do thing",
                "workspace_dir": "complete",
                "validation_steps": [
                    {"name": "v", "command": "true", "expected_exit_code": 0}
                ],
                "tags": ["test"],
            }
        )
    )
    adapter = GraduatedProblemSetAdapter(tmp_path)
    problems = adapter.load()
    assert [p.id for p in problems] == ["complete"]


def _write_problem(parent: Path, dir_name: str, problem_id: str) -> None:
    (parent / dir_name).mkdir()
    (parent / dir_name / "problem.json").write_text(
        json.dumps(
            {
                "id": problem_id,
                "title": problem_id,
                "difficulty": 1,
                "prompt": "do thing",
                "workspace_dir": dir_name,
                "validation_steps": [
                    {"name": "v", "command": "true", "expected_exit_code": 0}
                ],
                "tags": ["test"],
            }
        )
    )


def test_problem_ids_filter_returns_only_allowlisted(tmp_path):
    _write_problem(tmp_path, "001_alpha", "001_alpha")
    _write_problem(tmp_path, "002_beta", "002_beta")
    _write_problem(tmp_path, "003_gamma", "003_gamma")
    adapter = GraduatedProblemSetAdapter(
        tmp_path, problem_ids=["001_alpha", "003_gamma"]
    )
    assert [p.id for p in adapter.load()] == ["001_alpha", "003_gamma"]


def test_problem_ids_none_loads_everything(tmp_path):
    _write_problem(tmp_path, "001_alpha", "001_alpha")
    _write_problem(tmp_path, "002_beta", "002_beta")
    adapter = GraduatedProblemSetAdapter(tmp_path, problem_ids=None)
    assert {p.id for p in adapter.load()} == {"001_alpha", "002_beta"}


def test_problem_ids_with_unknown_id_silently_excludes(tmp_path):
    _write_problem(tmp_path, "001_alpha", "001_alpha")
    adapter = GraduatedProblemSetAdapter(tmp_path, problem_ids=["does_not_exist"])
    assert adapter.load() == []


def test_problem_ids_rejects_bare_string(tmp_path):
    import pytest

    with pytest.raises(TypeError, match="bare str"):
        GraduatedProblemSetAdapter(tmp_path, problem_ids="001_alpha")


def test_problem_ids_filter_skips_malformed_excluded_problem(tmp_path):
    """Allowlist must run before schema validation so a broken non-allowlisted
    problem.json doesn't abort the pinned acceptance test's load."""
    _write_problem(tmp_path, "001_alpha", "001_alpha")
    # 002_broken has valid JSON but is missing the required "difficulty" field
    (tmp_path / "002_broken").mkdir()
    (tmp_path / "002_broken" / "problem.json").write_text(
        json.dumps({"id": "002_broken", "title": "broken"})
    )
    adapter = GraduatedProblemSetAdapter(tmp_path, problem_ids=["001_alpha"])
    assert [p.id for p in adapter.load()] == ["001_alpha"]


def test_no_filter_still_validates_every_problem(tmp_path):
    """Without an allowlist, schema validation still runs on every problem —
    the pre-filter optimization must not weaken the default safety net."""
    import pytest

    _write_problem(tmp_path, "001_alpha", "001_alpha")
    (tmp_path / "002_broken").mkdir()
    (tmp_path / "002_broken" / "problem.json").write_text(
        json.dumps({"id": "002_broken", "title": "broken"})
    )
    adapter = GraduatedProblemSetAdapter(tmp_path)
    with pytest.raises(KeyError):
        adapter.load()
