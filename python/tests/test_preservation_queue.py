"""Preserved-error-trials derived view (ADR 0007 B1; pi-agent-space-1da)."""

from __future__ import annotations

from builders import make_eval_suite_ref, make_version_vector

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.domain.types import (
    Metrics,
    Outcome,
    Package,
    Trial,
)
from pi_evaluator.preservation_queue import preserved_error_trials


def _trial(trial_id: str) -> Trial:
    return Trial(
        trial_id=trial_id,
        package=Package(
            model="gemini-flash",
            system_prompt="",
            skills=[],
            template_values={},
        ),
        eval_suite_ref=make_eval_suite_ref(suite_id="coding_v1", suite_version="1.0.0"),
        version_vector=make_version_vector(
            pi_version="0.4.2",
            package_versions={},
            eval_suite_version="1.0.0",
        ),
    )


def _save_and_finalize(
    adapter: PerTrialDirectoryAdapter, trial_id: str, outcome: Outcome
) -> None:
    adapter.save_trial(_trial(trial_id))
    metrics = Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0)
    adapter.finalize_trial(trial_id, metrics, outcome)


def test_returns_only_error_escalated_trials(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    _save_and_finalize(adapter, "t-001", "completed")
    _save_and_finalize(adapter, "t-002", "error_escalated")
    _save_and_finalize(adapter, "t-003", "boundary_violation")
    _save_and_finalize(adapter, "t-004", "error_escalated")
    assert [t.trial_id for t in preserved_error_trials(adapter)] == ["t-002", "t-004"]


def test_returns_empty_when_no_trials_are_error_escalated(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    _save_and_finalize(adapter, "t-001", "completed")
    _save_and_finalize(adapter, "t-002", "boundary_violation")
    assert preserved_error_trials(adapter) == []


def test_excludes_open_trials_without_final_json(tmp_path):
    """A trial mid-flight (no final.json yet) has outcome=None and must
    not appear in the queue — the queue surfaces *resolved* failures
    awaiting human review, not in-progress work."""
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial("t-open"))
    _save_and_finalize(adapter, "t-failed", "error_escalated")
    assert [t.trial_id for t in preserved_error_trials(adapter)] == ["t-failed"]


def test_queue_is_durable_across_fresh_adapter_instances(tmp_path):
    """The queue is a scan, not in-memory state — a new adapter pointed
    at the same directory must see the same preserved trials."""
    writer = PerTrialDirectoryAdapter(tmp_path)
    _save_and_finalize(writer, "t-001", "error_escalated")
    _save_and_finalize(writer, "t-002", "completed")
    reader = PerTrialDirectoryAdapter(tmp_path)
    assert [t.trial_id for t in preserved_error_trials(reader)] == ["t-001"]
