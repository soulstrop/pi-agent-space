import json

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    SubjectiveScore,
    Trial,
    TrialEvent,
    VersionVector,
)
from pi_evaluator.ports.persistence_port import PersistencePort


def _trial(trial_id: str = "t-001") -> Trial:
    return Trial(
        trial_id=trial_id,
        package=Package(
            model="gemini-flash",
            system_prompt="be precise",
            skills=["lint"],
            template_values={"lang": "python"},
        ),
        eval_suite_ref=EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0"),
        version_vector=VersionVector(
            pi_version="0.4.2",
            package_versions={"lint": "1.0"},
            eval_suite_version="1.0.0",
        ),
    )


def test_adapter_satisfies_port_protocol(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    assert isinstance(adapter, PersistencePort)


def test_save_trial_writes_config_and_versions_files(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    t = _trial()
    adapter.save_trial(t)
    d = tmp_path / "t-001"
    assert (d / "config.json").exists()
    assert (d / "versions.json").exists()
    assert (d / "events.jsonl").exists()
    assert not (d / "final.json").exists()
    config = json.loads((d / "config.json").read_text())
    assert config["trial_id"] == "t-001"
    assert config["package"]["model"] == "gemini-flash"
    assert config["eval_suite_ref"]["suite_id"] == "coding_v1"


def test_append_event_appends_one_line_per_call(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    adapter.append_event(
        "t-001", TrialEvent(phase="configured", timestamp="t1", payload={"k": "v"})
    )
    adapter.append_event("t-001", TrialEvent(phase="eval", timestamp="t2"))
    lines = (tmp_path / "t-001" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["phase"] == "configured"
    assert json.loads(lines[1])["phase"] == "eval"


def test_append_is_order_preserving_across_repeated_calls(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    for i in range(5):
        adapter.append_event("t-001", TrialEvent(phase=f"e{i}", timestamp=f"t{i}"))
    lines = (tmp_path / "t-001" / "events.jsonl").read_text().splitlines()
    assert [json.loads(line)["phase"] for line in lines] == [
        "e0",
        "e1",
        "e2",
        "e3",
        "e4",
    ]


def test_finalize_writes_final_json(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    metrics = Metrics(tokens_consumed=100, validation_pass_rate=1.0, quality_score=0.9)
    adapter.finalize_trial("t-001", metrics, "completed")
    final = json.loads((tmp_path / "t-001" / "final.json").read_text())
    assert final["metrics"]["tokens_consumed"] == 100
    assert final["outcome"] == "completed"
    assert final["subjective_score"] is None


def test_finalize_with_subjective_score(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    metrics = Metrics(tokens_consumed=1, validation_pass_rate=1.0, quality_score=1.0)
    subj = SubjectiveScore(score=4.5, notes="ok", scorer="me", timestamp="t")
    adapter.finalize_trial("t-001", metrics, "completed", subj)
    final = json.loads((tmp_path / "t-001" / "final.json").read_text())
    assert final["subjective_score"]["score"] == 4.5


def test_finalize_records_error_escalated_outcome(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    metrics = Metrics(tokens_consumed=0, validation_pass_rate=0.0, quality_score=0.0)
    adapter.finalize_trial("t-001", metrics, "error_escalated")
    final = json.loads((tmp_path / "t-001" / "final.json").read_text())
    assert final["outcome"] == "error_escalated"


def test_round_trip_save_append_finalize_then_load(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    t = _trial()
    adapter.save_trial(t)
    adapter.append_event("t-001", TrialEvent(phase="configured", timestamp="t1"))
    adapter.append_event(
        "t-001",
        TrialEvent(phase="finalized", timestamp="t2", payload={"score": 1.0}),
    )
    metrics = Metrics(tokens_consumed=42, validation_pass_rate=0.5, quality_score=0.6)
    adapter.finalize_trial("t-001", metrics, "completed")

    [loaded] = adapter.load_trials()
    assert loaded.trial_id == "t-001"
    assert loaded.package == t.package
    assert loaded.eval_suite_ref == t.eval_suite_ref
    assert loaded.version_vector == t.version_vector
    assert [e.phase for e in loaded.events] == ["configured", "finalized"]
    assert loaded.events[1].payload == {"score": 1.0}
    assert loaded.final_metrics == metrics
    assert loaded.outcome == "completed"
    assert loaded.subjective_score is None


def test_partial_state_recovery_open_trial(tmp_path):
    """A trial without final.json loads as an open trial (final_metrics=None)."""
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    adapter.append_event("t-001", TrialEvent(phase="configured", timestamp="t1"))
    [loaded] = adapter.load_trials()
    assert loaded.final_metrics is None
    assert loaded.subjective_score is None
    assert len(loaded.events) == 1


def test_load_trials_skips_non_directory_entries(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial("t-001"))
    adapter.save_trial(_trial("t-002"))
    (tmp_path / "stray.txt").write_text("noise")
    loaded = adapter.load_trials()
    assert {t.trial_id for t in loaded} == {"t-001", "t-002"}


def test_load_trials_returns_empty_when_no_trials(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    assert adapter.load_trials() == []
