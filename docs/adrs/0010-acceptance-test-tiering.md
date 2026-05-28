# Title: 0010 - Acceptance-Test Tiering for Real-Pi Cost

**Status:** Accepted

## Context

Phase 3.5's acceptance test took ~7m51s for 2 runs at 4 trials × 1 problem against the cheapest available provider. The cost scales the wrong way under the rest of the plan:

- **Phase 4.1** introduces additional graduated problems. Per-trial cost multiplies by `n_problems`.
- **Phase 4.2** introduces `replicates`. Per-`(package, problem)` cost multiplies by `replicates` when opt-in.
- **Phase 6** raises trial counts above the ADR-0006 bootstrap threshold (~10), and surrogate-quality validation needs many more trials than that.

If the only marker is `@pytest.mark.acceptance` with production defaults, every acceptance test invocation pays the full multiplied cost. During v1 development we are deliberately budget-constrained — the tokens we burn validating the harness are tokens we cannot spend validating the optimizer. In production deployment pi-agent-space gets an explicit exploration budget; in the meantime, the dev/CI loop needs a cheap way to assert that the end-to-end pipeline still works without standing up a full-fidelity run.

The question this ADR closes (the Phase 4.1 hard block from the Open spikes table): split acceptance tests into a fast tier and a full tier, or accept full-fidelity real-Pi acceptance as CI-occasional and just document the budget?

## Options Considered

**A. Two markers (`acceptance_fast`, `acceptance_full`).** Each new acceptance test ships both variants. Fast = 1 trial · 0 retries · 1 problem · cheapest provider available. Full = production defaults. `mise run test` still excludes both; `test-acceptance-fast` is the dev/CI loop; `test-acceptance-full` is manual, run once per phase to prove the test's production-fidelity behavior.
- **Pros:** Dev/CI loop has a real end-to-end signal at near-zero cost. Full-fidelity behavior is still asserted, just not on every invocation. The fast/full split is explicit at the test layer where it belongs.
- **Cons:** Each new acceptance test costs ~2× authoring time (or at least a thin shared helper + two entry points). Risk that the fast variant drifts from the full variant and stops being a meaningful smoke.

**B. Single marker, budget-via-env-var.** Keep `acceptance`; have each test read `ACCEPTANCE_TIER=fast|full` from the environment and adjust trial budget / retry / problem count accordingly.
- **Pros:** One test function per phase. No duplication.
- **Cons:** Test selection is no longer reflected in pytest output (every run looks the same). CI configuration leaks into test internals. Harder to add a fast-only assertion (e.g., "this regression check needs a real model call but doesn't need to be cheap to be useful").

**C. Don't tier; accept that real-Pi acceptance is CI-occasional.** Document the per-phase budget in `docs/design-notes.md` and only run acceptance tests on a schedule (nightly, pre-release).
- **Pros:** Simplest mechanically. Forces honest accounting of the full-fidelity cost.
- **Cons:** No quick smoke signal during a Phase-4 implementation push. Regressions in the real-Pi path land on whoever runs the scheduled job, not on the PR that introduced them.

**D. Mock the real-Pi path in CI; only run real Pi locally.** A `MockPiSubprocessAdapter` returns canned event streams; CI runs against it.
- **Pros:** Free CI; no API key handling in CI.
- **Cons:** A mocked harness in CI is structurally identical to the Phase 1 stub already in the test suite — it stops being an end-to-end acceptance test the moment Pi's CLI surface diverges from the mock. Adds no signal over what Phase 1's acceptance test already provides.

## Decision

**Option A.** Two markers — `acceptance_fast` and `acceptance_full` — with the following rules:

- Each new acceptance test ships a fast variant alongside its full variant. Both call a shared `_run(...)` helper differing only in budget arguments. The fast variant is the dev/CI tier; the full variant is the once-per-phase production-fidelity tier.
- **Fast-tier budget definition:** 1 trial, 0 retries (`retry_budget=0`), 1 problem (`problem_ids=["001_binary_search"]`), cheapest provider available via the existing `_PROVIDER_FALLBACKS` order.
- **Full-tier budget definition:** the test's production defaults (whatever the phase calls for).
- **`pyproject.toml`:** `addopts = "-m 'not acceptance_fast and not acceptance_full'"` — default `mise run test` runs neither. Nothing real-Pi runs without explicit opt-in.
- **`mise.toml`:** `test-acceptance-fast`, `test-acceptance-full`, and `test-acceptance` (alias for `-m "acceptance_fast or acceptance_full"`).
- **Phase 1's acceptance test stays unmarked.** It uses stubs and costs zero tokens; the tiering scheme is about real-Pi cost, which Phase 1 doesn't have.
- **Existing Phase 2 and Phase 3 acceptance tests retag from `acceptance` to `acceptance_full`**, since they currently embody production-default behavior. Their fast variants are filed as follow-up work (one issue per phase).
- **Drift mitigation:** the shared `_run(...)` helper carries the pipeline assertions. The fast and full entry points differ only in the budget arguments they pass — so the assertion surface is identical and the fast variant cannot drift independently of the full variant.

## Reconsider Triggers

- **Token budget becomes generous.** If pi-agent-space lands a dedicated exploration budget covering routine full-fidelity runs in CI, drop the fast tier and run only full.
- **Fast-tier signal stops being trustworthy.** If a Phase 4 or Phase 6 regression slips past the fast tier because the budget is too small to exercise the failing code path, raise the fast-tier budget (still cheaper than full) or split into more tiers (fast / medium / full).
- **Shared `_run(...)` helper grows asymmetric.** If fast and full start needing genuinely different assertion logic — not just different budgets — the drift-mitigation argument collapses and the scheme needs revisiting (probably toward fully separate tests with a shared fixture).
- **CI-occasional turns out to be the right cadence anyway.** If `acceptance_full` never gets run except via the scheduled job, the manual-once-per-phase rule isn't actually being followed; reconsider Option C.

## Consequences

- Two pytest markers (`acceptance_fast`, `acceptance_full`) registered in `pyproject.toml`. The previous single `acceptance` marker is removed.
- Three mise tasks (`test-acceptance-fast`, `test-acceptance-full`, `test-acceptance`) replace the single previous `test-acceptance`.
- Existing Phase 2 and Phase 3 acceptance tests retag from `acceptance` to `acceptance_full` with no behavioral change.
- New acceptance tests in Phase 4+ are required to ship both variants; this becomes a phase-entry condition for any phase introducing a real-Pi acceptance test.
- Documentation referring to the `acceptance` marker by name (showboat demos, contributor guides) becomes stale and is updated alongside the marker rename, or accepted as a one-time stale-output cost.
- The Phase 4.1 hard block from the Open spikes table lifts; the per-spike row is removed.
- Phase 4.1's entry condition becomes: ship `test_acceptance_phase4_fast` + `test_acceptance_phase4_full`, per this ADR.
