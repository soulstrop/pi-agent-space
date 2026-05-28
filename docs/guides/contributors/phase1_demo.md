# Phase 1 Acceptance Test — End-to-End Trial Pipeline

*2026-05-28T03:02:56Z by Showboat 0.6.1*
<!-- showboat-id: 46ddb473-e9d7-4286-a9c6-e70cb45bd5ad -->

## Overview

`tests/test_acceptance_phase1.py` is the Phase-1 end-to-end smoke of the trial pipeline. It wires the real `TrialRunner`, the real `graduated_problems/` eval suite source, and the real per-trial-directory persistence against **stub** harness + **stub** scorer (Phase 2 swaps in the real CLI subprocess harness; Phase 3 swaps in the real scorer). What it proves is that the orchestration and on-disk shape are correct — the bits that don't depend on a live agent.

The pipeline under test produces a complete on-disk trial directory whose `events.jsonl` shows the canonical phase sequence: `configured → (eval, scored_objective)+ → finalized`.

The rest of this document walks the features that test exercises. All commands below run from the `python/` directory.

## Feature 1 — The `Package` abstraction

A `Package` is the unit of configuration being evaluated: a model, a system prompt, a skill subset, and template values. In Phase 1 the package is hand-coded as a baseline (`gemini-flash` + a generic prompt + read/write/edit/bash skills); later phases will produce packages from the slot space and optimizer.

```bash
sed -n '35,45p' tests/test_acceptance_phase1.py
```

```python 
def _baseline_package() -> Package:
    """The Phase-1 baseline: gemini-flash + a generic system prompt and
    a minimal tool/skill subset. Phase 2 supplies the real prompt and
    tool list when the CliSubprocessAdapter lands."""
    return Package(
        model="gemini-flash",
        system_prompt="You are a careful coding assistant.",
        skills=["read", "write", "edit", "bash"],
        template_values={},
    )

```

## Feature 2 — `TrialRunner` orchestration

`TrialRunner` is the orchestrator. It takes four ports (`harness`, `scorer`, `persistence`, `suite_source`) plus an injectable clock, and exposes a single `run_trial(...)` entry point that walks the pipeline and emits the event stream. Phase 1 verifies that the orchestration shape is right *before* any real adapter is plugged in — the stubs let us prove the contract without depending on a live model.

```bash
sed -n '47,80p' tests/test_acceptance_phase1.py
```

```python 
def test_phase1_acceptance_end_to_end(tmp_path):
    persistence = PerTrialDirectoryAdapter(tmp_path)
    suite_source = GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR)
    harness = StubAgentHarnessAdapter(
        telemetry=RawTelemetry(events=[{"kind": "tok", "n": 1234}], exit_code=0)
    )
    scorer = StubScorer(
        metrics=Metrics(
            tokens_consumed=1234,
            validation_pass_rate=1.0,
            quality_score=0.95,
        )
    )
    runner = TrialRunner(
        harness=harness,
        scorer=scorer,
        persistence=persistence,
        suite_source=suite_source,
        clock=lambda c=itertools.count(): f"2026-05-06T00:00:{next(c):02d}Z",
    )

    suite_ref = EvalSuiteRef(suite_id="coding_v1", suite_version="0.1.0")
    versions = VersionVector(
        pi_version="0.4.2",
        package_versions={"read": "1.0", "write": "1.0", "edit": "1.0", "bash": "1.0"},
        eval_suite_version="0.1.0",
    )

    trial = runner.run_trial(
        trial_id="t-acceptance-001",
        package=_baseline_package(),
        eval_suite_ref=suite_ref,
        version_vector=versions,
    )
```

## Feature 3 — Eval-suite source: `GraduatedProblemSetAdapter`

The suite-source port abstracts "where do problems come from?". The Phase-1 adapter reads the on-disk `graduated_problems/` directory at the repo root. Each numbered subdirectory is one problem the harness will be asked to solve.

```bash
ls ../graduated_problems/
```

```output
001_binary_search
```

## Feature 4 — Persistence: `PerTrialDirectoryAdapter`

Persistence is contract-defined: every trial lands as a directory containing exactly four files. The test asserts all four exist and that their contents are well-formed.

| File           | Contents                                                                 |
|----------------|--------------------------------------------------------------------------|
| `config.json`  | The frozen trial config: `trial_id`, `package`, `eval_suite_ref`.         |
| `versions.json`| The `VersionVector` — Pi version, per-package versions, suite version.   |
| `events.jsonl` | The append-only event stream, one JSON event per line.                  |
| `final.json`   | The terminal record: aggregated metrics + (eventual) subjective score.  |

Phase 1 keeps the subjective-score slot present but `null` — Phase 4+ will populate it.

## Feature 5 — The phased event stream

The most load-bearing assertion in this test is the *shape* of `events.jsonl`:

- The first event is always `configured`.
- The last event is always `finalized`.
- The middle is one `(eval, scored_objective)` pair per problem, in order.

This is the canonical "trial as event stream with phased scoring" contract — config → eval → objective → (subjective) → final. Phase 1 exercises only the objective leg; the subjective leg is wired but not driven.

```bash
sed -n '101,118p' tests/test_acceptance_phase1.py
```

```python 
    event_lines = (trial_dir / "events.jsonl").read_text().splitlines()
    phases = [json.loads(ln)["phase"] for ln in event_lines]
    assert phases[0] == "configured"
    assert phases[-1] == "finalized"
    middle = phases[1:-1]
    # Each problem produces one (eval, scored_objective) pair, in order.
    assert len(middle) % 2 == 0
    assert all(middle[i] == "eval" for i in range(0, len(middle), 2))
    assert all(middle[i] == "scored_objective" for i in range(1, len(middle), 2))

    n_problems = len(middle) // 2
    assert n_problems >= 1, "expected at least 001_binary_search to be loaded"

    final = json.loads((trial_dir / "final.json").read_text())
    assert final["metrics"]["tokens_consumed"] == 1234 * n_problems
    assert final["metrics"]["validation_pass_rate"] == 1.0
    assert final["metrics"]["quality_score"] == 0.95
    assert final["subjective_score"] is None
```

## Feature 6 — Metric aggregation across problems

`tokens_consumed` is summed across problems (`1234 * n_problems`), while rates like `validation_pass_rate` and `quality_score` pass through from the stub. This pins down that the aggregator handles count-like and ratio-like metrics differently — a contract Phase 3's real scorer will need to honor.

## Feature 7 — Round-trip persistence

The final assertion block does two equivalence checks:

1. The in-memory `Trial` returned by `run_trial` matches what landed on disk.
2. Loading the trial back through `persistence.load_trials()` reconstructs an equal `Trial` — same id, same final metrics, same event phase sequence.

This is what makes the persistence adapter actually a port and not just a write-side logger: the read path is contract-checked too.

```bash
sed -n '120,130p' tests/test_acceptance_phase1.py
```

```python 
    # Returned in-memory Trial agrees with what landed on disk.
    assert trial.trial_id == "t-acceptance-001"
    assert trial.final_metrics is not None
    assert trial.final_metrics.tokens_consumed == 1234 * n_problems
    assert [e.phase for e in trial.events] == phases

    # Round-trip through the persistence adapter recovers the same trial.
    [reloaded] = persistence.load_trials()
    assert reloaded.trial_id == trial.trial_id
    assert reloaded.final_metrics == trial.final_metrics
    assert [e.phase for e in reloaded.events] == phases
```

## Proof — the test passes

The whole point of an acceptance test is that it actually runs. Re-executing it here:

```bash
uv run pytest tests/test_acceptance_phase1.py -v 2>&1 | tail -10
```

```output
============================= test session starts ==============================
platform linux -- Python 3.13.12, pytest-9.0.3, pluggy-1.6.0 -- /home/mikeco/projects/pi-agent-space/python/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/mikeco/projects/pi-agent-space/python
configfile: pyproject.toml
collecting ... collected 1 item

tests/test_acceptance_phase1.py::test_phase1_acceptance_end_to_end PASSED [100%]

============================== 1 passed in 0.03s ===============================
```

```bash
uv run pytest tests/test_acceptance_phase1.py -v 2>&1 | tail -10 | sed -E 's/in [0-9.]+s/in N.NNs/'
```

```output
============================= test session starts ==============================
platform linux -- Python 3.13.12, pytest-9.0.3, pluggy-1.6.0 -- /home/mikeco/projects/pi-agent-space/python/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/mikeco/projects/pi-agent-space/python
configfile: pyproject.toml
collecting ... collected 1 item

tests/test_acceptance_phase1.py::test_phase1_acceptance_end_to_end PASSED [100%]

============================== 1 passed in N.NNs ===============================
```
