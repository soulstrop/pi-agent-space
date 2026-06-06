"""Unit tests for the tolerant dataclass reader (ADR 0019 D4/D8)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pi_evaluator.domain.tolerant_read import tolerant


@dataclass(frozen=True)
class _Sample:
    a: int
    b: str = "default-b"


def test_constructs_when_keys_match_exactly():
    got = tolerant(_Sample, {"a": 1, "b": "x"}, where="t")
    assert got == _Sample(a=1, b="x")


def test_drops_unknown_keys():
    got = tolerant(_Sample, {"a": 1, "b": "x", "c": "future", "d": 9}, where="t")
    assert got == _Sample(a=1, b="x")


def test_logs_info_naming_unknown_fields(caplog):
    with caplog.at_level(logging.INFO, logger="pi_evaluator"):
        tolerant(_Sample, {"a": 1, "c": "future", "d": 9}, where="versions.json")
    records = [r for r in caplog.records if getattr(r, "event", None) == "ignored_unknown_fields"]
    assert len(records) == 1
    assert records[0].unknown_fields == ["c", "d"]
    assert records[0].where == "versions.json"


def test_no_log_when_no_unknown_keys(caplog):
    with caplog.at_level(logging.INFO, logger="pi_evaluator"):
        tolerant(_Sample, {"a": 1, "b": "x"}, where="t")
    assert not [
        r for r in caplog.records if getattr(r, "event", None) == "ignored_unknown_fields"
    ]


def test_absent_field_with_default_falls_back():
    """Backward-compat (D3): an older file missing an additive field uses the default."""
    got = tolerant(_Sample, {"a": 1}, where="t")
    assert got == _Sample(a=1, b="default-b")
