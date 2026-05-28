# Phase 2 Acceptance Test — Real Pi Against the Coding Suite

*2026-05-28T03:17:50Z by Showboat 0.6.1*
<!-- showboat-id: ef4b76c7-5dab-4506-8f3d-ee1bdec9287b -->

## Overview

`tests/test_acceptance_phase2.py` is the Phase-2 end-to-end acceptance test. Where Phase 1 proved the orchestration shape against stubs, Phase 2 swaps in two **real** adapters:

- `CliSubprocessAdapter` — spawns the real `pi` binary in a materialized workspace.
- `SyntheticSuiteScorer` — derives `Metrics` from the resulting telemetry, no longer canned.

The eval-suite source, persistence adapter, runner, and event-stream contract are unchanged from Phase 1 — that continuity is itself part of what the test proves. All commands below run from the `python/` directory.

## Feature 1 — Marker-gated AND prerequisite-gated

The test is gated two ways. The `@pytest.mark.acceptance` decorator excludes it from the default `mise run test` (which uses `addopts = "-m 'not acceptance'"`); you opt in via `mise run test-acceptance`. Even then, runtime guards skip the test cleanly if the `pi` binary or any provider API key is missing.

```python
@pytest.mark.acceptance
def test_phase2_acceptance_end_to_end(tmp_path):
    if shutil.which("pi") is None:
        pytest.skip("`pi` binary not on PATH")
    model = _detect_model()
    if model is None:
        pytest.skip(
            "no provider API key found "
            f"(looked for: {', '.join(v for v, _ in _PROVIDER_FALLBACKS)})"
        )
```

## Feature 2 — Provider fallback

Rather than hard-coding a single model, the test walks a preference list and picks the first provider whose API key is present in the environment. This keeps the test runnable across whichever credential the developer happens to have, while still being deterministic about which model wins.

```python
_PROVIDER_FALLBACKS: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "google/gemini-2.5-flash"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
]


def _detect_model() -> str | None:
    for env_var, model in _PROVIDER_FALLBACKS:
        if os.environ.get(env_var):
            return model
    return None
```

## Feature 3 — `CliSubprocessAdapter` and `SyntheticSuiteScorer`

This is the core Phase-2 substitution: two `Stub*` adapters become real. `CliSubprocessAdapter(pi_binary="pi")` spawns Pi as a subprocess in a materialized workspace per problem; `SyntheticSuiteScorer()` consumes the resulting telemetry and produces `Metrics`. The rest of the runner wiring is identical to Phase 1.

```python
    persistence = PerTrialDirectoryAdapter(tmp_path)
    runner = TrialRunner(
        harness=CliSubprocessAdapter(pi_binary="pi"),
        scorer=SyntheticSuiteScorer(),
        persistence=persistence,
        suite_source=GraduatedProblemSetAdapter(GRADUATED_PROBLEMS_DIR),
    )
```

## Feature 4 — Pipeline shape unchanged from Phase 1

The same four files (`config.json`, `versions.json`, `events.jsonl`, `final.json`) must materialize, and `events.jsonl` must still walk `configured → (eval, scored_objective)+ → finalized`. This is the load-bearing continuity check: swapping in real adapters must not perturb the contract. If Phase 2 had to re-litigate the event-stream shape every time a stub was replaced, the layering would be wrong.

## Feature 5 — Outcome classification (ADR 0007)

Phase 2 adds an `outcome` field to `final.json` and to the in-memory `Trial`. It must be one of three known values: `completed`, `boundary_violation`, or `error_escalated`. The test asserts both that the value is in the allowed set and that the on-disk and in-memory views agree.

```python
    # ADR 0007 outcome classification: must be set, must be a known value.
    assert final["outcome"] in {"completed", "boundary_violation", "error_escalated"}
    assert trial.outcome == final["outcome"]
```

## Feature 6 — Quality deliberately NOT asserted

The test docstring is explicit: _"We assert pipeline mechanics (files written, events flow, final metrics computed). We do NOT assert that the agent actually solved the problem — that is a separate quality question and would make the test flaky against model nondeterminism."_

This is a deliberate scope choice. Phase 2 is about wiring the real harness and scorer into the trial pipeline, not about measuring whether any particular model can solve `001_binary_search`. Quality lives elsewhere — in the metrics distributions produced by many trials across many packages, which is what the optimizer driver consumes.

## Proof — the test runs (or skips cleanly)

Because Phase 2 talks to a real model, the test only *runs* when a provider API key is set. To exercise the gating from both sides, we first show what `pi` and API-key availability look like in this environment, then ask pytest to collect the acceptance marker.

```bash
which pi && for k in GEMINI_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do if [ -n "${!k}" ]; then echo "$k: set"; else echo "$k: unset"; fi; done
```

```output
/home/mikeco/.local/share/mise/installs/pi/0.76.0/pi
GEMINI_API_KEY: unset
ANTHROPIC_API_KEY: unset
OPENAI_API_KEY: unset
```

```bash
uv run pytest tests/test_acceptance_phase2.py -m acceptance -v -rs 2>&1 | tail -10 | sed -E 's/in [0-9.]+s/in N.NNs/'
```

```output
cachedir: .pytest_cache
rootdir: /home/mikeco/projects/pi-agent-space/python
configfile: pyproject.toml
collecting ... collected 1 item

tests/test_acceptance_phase2.py::test_phase2_acceptance_end_to_end SKIPPED [100%]

=========================== short test summary info ============================
SKIPPED [1] tests/test_acceptance_phase2.py:66: no provider API key found (looked for: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY)
============================== 1 skipped in N.NNs ==============================
```

## What changed from Phase 1

| Concern               | Phase 1                                 | Phase 2                                   |
|-----------------------|-----------------------------------------|-------------------------------------------|
| Agent harness         | `StubAgentHarnessAdapter` (canned)      | `CliSubprocessAdapter` (real `pi` binary) |
| Objective scorer      | `StubScorer` (canned metrics)           | `SyntheticSuiteScorer` (derived from telemetry) |
| Model selection       | Hard-coded `gemini-flash` in fixture    | Provider fallback over env-var keys       |
| Gating                | Runs in default suite                   | `@pytest.mark.acceptance` + runtime skip  |
| `final.outcome`       | Not present                             | One of `completed` / `boundary_violation` / `error_escalated` (ADR 0007) |
| Quality assertion     | Stub metrics asserted by value          | Deliberately none — pipeline mechanics only |
| Suite source / persistence / runner / event stream | — | unchanged |

Phase 3 will swap the remaining piece — replacing `SyntheticSuiteScorer` with the real, validation-driven scorer — while keeping everything Phase 2 just locked down.
