import json

from pi_evaluator.adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from pi_evaluator.domain.types import (
    EvalSuiteRef,
    Metrics,
    Package,
    RunConfig,
    RunEvent,
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


def test_trial_run_id_round_trips_through_config_json(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    t = _trial()
    t.run_id = "run-abc"
    adapter.save_trial(t)
    config = json.loads((tmp_path / "t-001" / "config.json").read_text())
    assert config["run_id"] == "run-abc"
    [loaded] = adapter.load_trials()
    assert loaded.run_id == "run-abc"


def test_trial_without_run_id_loads_as_none(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.save_trial(_trial())
    # Manually remove run_id to simulate pre-ADR-0013 trial on disk
    config_path = tmp_path / "t-001" / "config.json"
    config = json.loads(config_path.read_text())
    del config["run_id"]
    config_path.write_text(json.dumps(config))
    [loaded] = adapter.load_trials()
    assert loaded.run_id is None


# ------------------------------------------------------------------
# Run directory tests (ADR 0013)
# ------------------------------------------------------------------

def _run_config() -> RunConfig:
    return RunConfig(
        eval_suite_ref=EvalSuiteRef(suite_id="coding_v1", suite_version="1.0.0"),
        version_vector=VersionVector(
            pi_version="0.74.0",
            package_versions={},
            eval_suite_version="1.0.0",
        ),
        trial_budget=5,
        per_trial_cost_cap_usd=1.0,
        per_run_cost_cap_usd=4.0,
    )


def test_create_run_writes_directory_and_files(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.create_run("run-001", _run_config())
    run_dir = tmp_path / "runs" / "run-001"
    assert run_dir.is_dir()
    assert (run_dir / "run_config.json").exists()
    assert (run_dir / "run_events.jsonl").exists()
    assert (run_dir / "trial_manifest.jsonl").exists()


def test_create_run_writes_config_fields(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.create_run("run-001", _run_config())
    cfg = json.loads((tmp_path / "runs" / "run-001" / "run_config.json").read_text())
    assert cfg["run_id"] == "run-001"
    assert cfg["trial_budget"] == 5
    assert cfg["per_trial_cost_cap_usd"] == 1.0
    assert cfg["per_run_cost_cap_usd"] == 4.0


def test_append_run_event_adds_line(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.create_run("run-001", _run_config())
    adapter.append_run_event(
        "run-001",
        RunEvent(phase="run_started", timestamp="t1", payload={"trial_budget": 5}),
    )
    adapter.append_run_event(
        "run-001",
        RunEvent(phase="run_halted", timestamp="t2", payload={"halted_reason": "budget"}),
    )
    lines = (
        tmp_path / "runs" / "run-001" / "run_events.jsonl"
    ).read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["phase"] == "run_started"
    assert json.loads(lines[1])["phase"] == "run_halted"
    assert json.loads(lines[1])["payload"]["halted_reason"] == "budget"


def test_record_trial_dispatched_and_closed_append_to_manifest(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.create_run("run-001", _run_config())
    adapter.record_trial_dispatched("run-001", "t-aaa")
    adapter.record_trial_closed("run-001", "t-aaa", "completed")
    adapter.record_trial_dispatched("run-001", "t-bbb")
    lines = (
        tmp_path / "runs" / "run-001" / "trial_manifest.jsonl"
    ).read_text().splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first["status"] == "dispatched"
    assert first["trial_id"] == "t-aaa"
    assert "timestamp" in first
    second = json.loads(lines[1])
    assert second["status"] == "closed"
    assert second["outcome"] == "completed"
    assert json.loads(lines[2])["trial_id"] == "t-bbb"


def test_load_trials_ignores_runs_subdirectory(tmp_path):
    adapter = PerTrialDirectoryAdapter(tmp_path)
    adapter.create_run("run-001", _run_config())
    adapter.save_trial(_trial("t-001"))
    loaded = adapter.load_trials()
    assert len(loaded) == 1
    assert loaded[0].trial_id == "t-001"
