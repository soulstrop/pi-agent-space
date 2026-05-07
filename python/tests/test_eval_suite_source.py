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
