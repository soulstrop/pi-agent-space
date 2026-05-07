from pathlib import Path

import pytest

from pi_evaluator.adapters.workspace import materialize_workspace


def test_materialize_returns_existing_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("hello")
    dest = materialize_workspace(src)
    assert dest.is_dir()


def test_materialize_copies_top_level_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("alpha")
    (src / "b.py").write_text("print('hi')")
    dest = materialize_workspace(src)
    assert (dest / "a.txt").read_text() == "alpha"
    assert (dest / "b.py").read_text() == "print('hi')"


def test_materialize_copies_nested_directories(tmp_path):
    src = tmp_path / "src"
    (src / "sub" / "deep").mkdir(parents=True)
    (src / "sub" / "deep" / "x.txt").write_text("x")
    dest = materialize_workspace(src)
    assert (dest / "sub" / "deep" / "x.txt").read_text() == "x"


def test_materialize_destination_is_independent_of_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("original")
    dest = materialize_workspace(src)
    (dest / "file.txt").write_text("mutated")
    (dest / "new.txt").write_text("added")
    assert (src / "file.txt").read_text() == "original"
    assert not (src / "new.txt").exists()


def test_materialize_returns_distinct_paths_per_call(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x")
    a = materialize_workspace(src)
    b = materialize_workspace(src)
    assert a != b
    assert a.is_dir() and b.is_dir()


def test_materialize_rejects_non_directory(tmp_path):
    src = tmp_path / "not-a-dir.txt"
    src.write_text("oops")
    with pytest.raises(ValueError):
        materialize_workspace(src)


def test_materialize_rejects_missing_path(tmp_path):
    with pytest.raises(ValueError):
        materialize_workspace(tmp_path / "does-not-exist")


def test_materialize_with_str_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x")
    dest = materialize_workspace(str(src))
    assert isinstance(dest, Path)
    assert (dest / "f").read_text() == "x"
