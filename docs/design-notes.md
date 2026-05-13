# Design Notes

This document captures **non-obvious design choices** in pi-agent-space — the
kind a future reader might encounter and think *"huh, I wonder why."* It is
deliberately lighter-weight than [ADRs](adrs/), which are reserved for
consequential architectural commitments. Notes here are appendable; each entry
stands alone.

When a note grows in scope, accumulates real consequences, or starts being
referenced in commit messages and design discussions, **promote it to an ADR**.

---

## Format

Each entry uses this skeleton:

```
## {Topic}
**Where:** {file paths or module names}
**Decision:** {one-line statement}

{1–3 paragraphs of context and why}

**Related:** {ADRs, code, tests, memory pointers — optional}
```

New entries go at the bottom of the **Notes** section. Don't reorder existing
entries; the document is an append-only log.

---

## Notes

### Per-trial directory: four files instead of three or two

**Where:** `python/src/pi_evaluator/adapters/per_trial_directory_adapter.py`; ADR 0003.

**Decision:** Each trial directory contains four separate files (`config.json`, `versions.json`, `events.jsonl`, `final.json`), not a consolidated single file or a three-file collapse.

The most defensible candidate consolidation is folding `versions.json` into `config.json` since the version vector is small. We keep them separate because they answer different questions about a trial: `config.json` is *what we proposed*, `versions.json` is *what was actually frozen at trial start*. They diverge whenever the package definition references skills that resolve to different versions over time. Keeping them separate makes the version vector independently greppable across trials without parsing the whole config — which matters once trials accumulate.

The four-file layout is fixed by ADR 0003. Reconsider if (a) per-trial inode pressure becomes real (ADR 0003's >10K trigger), (b) cross-trial queries push us to SQLite, or (c) the version vector grows beyond the small struct it is today.

**Related:** [ADR 0003 — Trial Persistence Strategy](adrs/0003-trial-persistence.md).

---

### ScoringPort: two methods, not one

**Where:** `python/src/pi_evaluator/ports/scoring_port.py`.

**Decision:** `ScoringPort` exposes `score_objective(telemetry) -> Metrics` and `score_subjective(trial) -> SubjectiveScore | None` as separate methods rather than a single unified scoring call.

The two methods mirror Bockeler's computational/inferential split (see `docs/terminology.md` and the math.pdf addendum on user-harness feedback as a lens). Computational scoring is deterministic, fast, and fully observed at trial close — it can run synchronously inside the trial loop. Inferential scoring (LLM judge, human rating) is slow, async, and may never produce a value for a given trial. Collapsing them into one method would force every adapter to either block on subjective scoring or invent a partial-result protocol; the two-method split lets each return its native type.

`score_subjective` takes a full `Trial` (not just a `trial_id`) because subjective scoring may want to inspect the trial's events, configuration, or prior metrics before producing a rating. Passing the trial is more honest about what the contract permits the implementation to look at.

**Related:** `docs/math.pdf` Appendix A; memory `project_inference_vs_computation.md`.

---

### Candidate identity: skills order is significant

> **Superseded** by *Skills are an unordered set* (below). Pi 0.74 confirmed `--tools` is order-insensitive; the conservative guess captured here did not survive contact with Pi.

**Where:** `python/src/pi_evaluator/domain/identity.py`.

**Decision:** The candidate-identity hash treats `skills` list order as significant; reordering the list produces a different hash.

The package's `skills` represents an ordered pipeline rather than a set: by convention, `["lint", "format", "test"]` and `["test", "format", "lint"]` are semantically distinct because pipeline ordering can change agent behavior at runtime. Order-significance is the conservative default — if two semantically-equivalent reorderings turn out to map to the same effective behavior, that fact emerges as a known-equivalent substitution catalogued by the proposer (Phase 3.2 onward), not as a hash collapse.

Latent concerns that would force revision: (a) if a future ADR ever decides skills should be unordered (a set), the canonicalization changes and any cached hashes become invalid, which would mean a one-time recomputation pass over `trials/`; (b) if international template values ever introduce non-ASCII text, NFC normalization may need to enter the canonical form ahead of `json.dumps`.

**Related:** `python/tests/test_identity.py`; memory `project_inference_vs_computation.md` (substitution principle).

---

### Pi invocation: canonical command shape

**Where:** `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py`.

**Decision:** The Phase 2 adapter invokes Pi as `pi --print --no-session --mode json --model <provider/id> [--system-prompt <text>] [--tools <csv>] "<prompt>"` and parses the JSON event stream off stdout. `--print` is non-interactive (one-shot prompt + exit); `--no-session` means ephemeral (no session jsonl persisted); `--mode json` produces line-delimited events.

This shape is the result of reading Pi's `docs/json.md` and `docs/usage.md` once and committing to a stable invocation: every trial across every phase uses the same flag set. The optional flags (`--system-prompt`, `--tools`) are omitted when the corresponding Package field is empty so Pi falls back to its defaults rather than receiving empty strings.

Reconsider triggers: (a) if we want a Pi session jsonl per trial as a debug trail, drop `--no-session` and add `--session-dir <trial_workspace>/.pi-session` so sessions stay per-trial-isolated; (b) if streaming feedback into the trial as it happens becomes useful (rather than parsing after exit), switch from `subprocess.run` to a streaming reader.

**Related:** `python/tests/test_cli_subprocess_adapter.py`; Pi local docs at `~/.local/share/mise/installs/pi/<version>/docs/json.md`.

---

### Provider/model as a unified `provider/id` string

**Where:** `python/src/pi_evaluator/domain/types.py` (`Package.model`); `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py`.

**Decision:** `Package.model` is a single string of the form `"<provider>/<id>"` (e.g., `"google/gemini-2.5-flash"`, `"anthropic/claude-haiku-4-5"`), passed verbatim to Pi's `--model` flag. We did **not** split the field into `model_provider` + `model_id`.

Pi's CLI accepts both forms (`--provider X --model Y` or `--model X/Y`); choosing the unified string keeps the Package surface area smaller, makes the candidate-identity hash trivially stable across provider rearrangements, and lets the slot-space schema enumerate `(provider, model)` tuples as opaque strings rather than coupled fields. Future featurization (Phase 6.1) will likely split the string back into provider and id features for the surrogate, but the storage form stays unified.

Reconsider triggers: (a) provider-specific config (deployment regions, API base URLs) needs to ride alongside the model selection; (b) the optimizer wants to vary provider and id semi-independently and the slot schema bumps into the unified-string form.

**Related:** `python/src/pi_evaluator/domain/types.py:Package`.

---

### Validation always runs, even when Pi exits non-zero

**Where:** `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py`.

**Decision:** After Pi exits, the adapter runs every `ValidationStep.command` against the materialized workspace regardless of Pi's exit code. The exit code is preserved in `RawTelemetry.exit_code` for downstream signals; validation results are independent.

The workspace state IS the experimental result. Pi might exit non-zero for many reasons — API rate limits, malformed events, an explicit error from the model — that don't preclude the workspace having been productively modified. Conversely Pi might exit zero having done nothing useful. Decoupling validation from Pi's exit code lets the scorer treat both signals as independent observations: tokens-consumed says how expensive the run was; validation-pass-rate says whether the workspace ended in a passing state; exit code says whether the harness itself succeeded.

This also matters for adversarial / chaotic test cases where we deliberately want to score "what state did the workspace end in" without conflating it with "did Pi crash."

**Related:** `python/tests/test_validation.py::test_validation_runs_even_when_pi_fails`.

---

### Skills are Pi tool names verbatim

**Where:** `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py`; `python/src/pi_evaluator/domain/types.py` (`Package.skills`).

**Decision:** `Package.skills` is a `list[str]` whose entries are passed comma-joined into Pi's `--tools` flag without translation, mapping, or namespacing. Valid values are Pi's built-in tool names (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`) plus any extension-installed tool names registered via `pi install`.

The Phase 1 plan referred to skills generically (`["lint", "format"]`), which made sense before the Pi binding. Phase 2 forces the term: a "skill" in our package model is exactly an entry in Pi's `--tools` set. The Phase 3.1 slot schema must therefore enumerate valid Pi tool names per the running Pi installation, and reject invalid names at schema-load time so a proposed package can actually run.

A future broader notion of "skill" — e.g., a higher-level capability composed of multiple Pi tools and a snippet of system prompt — would need a different field name (`capabilities`?) or a translation layer. Today the term and the data are unified.

**Related:** Pi local docs at `~/.local/share/mise/installs/pi/<version>/index.md`; Phase 3.1 in `docs/implementation-plan.md`.

---

### Skills are an unordered set (supersedes earlier note)

**Where:** `python/src/pi_evaluator/domain/identity.py`; `python/src/pi_evaluator/domain/types.py` (`Package.skills`).

**Decision:** `Package.skills` is set-valued at the semantic level. The candidate-identity hash sorts the list before hashing, so `["read", "bash"]` and `["bash", "read"]` produce the same identity.

**Supersedes** the earlier note "Candidate identity: skills order is significant." The earlier note was a conservative guess made before Phase 2 closeout's checkpoint review; verifying against Pi 0.74 showed `--tools` is order-insensitive — every skill in the list is registered for execution and ordering does not affect what Pi runs. Treating order as significant would have wasted the optimizer's budget proposing `[read, bash]` and `[bash, read]` as distinct candidates that Pi runs identically.

The field type stays `list[str]` (not `set[str]`) so JSON serialization in `config.json` and the events stream stays stable and ordered. The semantic-vs-storage split is captured in `_canonicalize_package` in `identity.py`.

If a future skill mechanism introduces a higher-level "capability pipeline" where order *is* load-bearing, that's a different field with a different type — don't repurpose `skills`.

**Related:** `python/tests/test_identity.py::test_reordered_skills_hash_equal`; commit `1f1b4c4`.

---

### Trial outcome classifier: v1 rule

**Where:** `python/src/pi_evaluator/trial_runner.py` (`_classify_outcome`, `_has_model_error`).

**Decision:** A trial is `error_escalated` if **any** problem's `RawTelemetry` shows either (a) a non-zero subprocess exit code, or (b) an assistant `message_end` event with `stopReason == "error"`. Otherwise — absent a boundary trip from the cost-cap watchdog — the trial is `completed`. The cost-cap watchdog in `run_trial` sets `boundary_violation` directly when `per_trial_cost_cap_usd` is crossed, bypassing this classifier; subprocess timeouts remain unimplemented.

The acceptance test on a Pi run with an expired API key is the motivating case: Pi exits 0 (it ran cleanly), but every assistant `message_end` carries `stopReason: "error"` from the provider's rejected request. Without rule (b), the trial would close as `completed` with zero metrics — a silent degradation that ADR 0007 explicitly rules out.

The classifier deliberately does not flag empty event streams or zero `totalTokens` as errors: a zero-token completed run is just a vacuous success and the surrogate sees it as such (low quality, low cost). The classifier flags only signals that say *something failed*.

Phase 3.4 grows the rule with `boundary_violation` triggers — the `per_trial_cost_cap_usd` watchdog is wired in `run_trial` now (per-run cap halts the driver between trials rather than producing a boundary-violated trial); subprocess `TimeoutExpired` and the adapter-layer retry budget (`error_escalated` only after retries exhaust) remain to land.

**Related:** [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md); `python/tests/test_trial_runner.py::test_run_trial_classifies_*`; commit `61fc31e`.

---

### Tempdir cleanup deferred to OS reaping

**Where:** `python/src/pi_evaluator/adapters/workspace.py`.

**Decision:** `materialize_workspace` calls `tempfile.mkdtemp` and never explicitly cleans up. v1 trusts the OS — `systemd-tmpfiles` (or equivalent) — to reap stale tmpdirs.

The interaction with ADR 0007's preservation requirement is the reason we *don't* add a try/finally cleanup: when a trial closes as `error_escalated`, the materialized workspace MUST outlive the trial so a human can inspect what Pi was doing when it failed. A naive cleanup hook in the adapter would delete exactly the evidence we need.

Phase 3.4 will need to make this explicit: cleanup on `completed` (and possibly `boundary_violation`) outcomes, preserve on `error_escalated`. That decision is paired with the persistent-error preservation queue, so it lands together rather than piecemeal.

If multi-trial runs at Phase 4 cadence reveal a real leak (disk pressure, inode exhaustion), revisit immediately — that is one of ADR 0004's reconsider triggers.

**Related:** [ADR 0004 — Workspace Isolation Strategy](adrs/0004-workspace-isolation.md); [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md).

---

### Cost-cap enforcement: between-step polling, single warning fraction

**Where:** `python/src/pi_evaluator/trial_runner.py` (`COST_CAP_WARNING_FRACTION`, `run_trial` cost-cap loop); `python/src/pi_evaluator/optimizer_driver.py` (`run` cumulative-cost check).

**Decision:** Cost-cap enforcement is **between-step polling**, not a parallel watchdog: the per-trial cap is checked after each problem's `scored_objective` event inside `TrialRunner.run_trial`; the per-run cap is checked after each trial completes inside `OptimizerDriver.run`. The "two thresholds" commitment from ADR 0005 is realized as a single configurable hard cap (`per_trial_cost_cap_usd`, `per_run_cost_cap_usd`) plus a fixed warning fraction `COST_CAP_WARNING_FRACTION = 0.8` of that cap. Warning events for per-trial caps land in the trial event stream as `cost_cap_warning` (phase) with `scope="per_trial"`; per-run warnings are emitted via Python `logging.warning` on the driver's logger rather than as trial events, because they cross trial boundaries and the trial-event invariant is *"`finalized` is the last event"*.

The between-step approach was chosen over a parallel signal-handling watchdog for v1 because Pi runs are short relative to step granularity, the harness is `subprocess.run` not a streaming reader, and intra-step kill (SIGTERM/SIGKILL of a running Pi) carries cleanup hazards (half-mutated workspace, partial event stream) that we'd rather not engage with until ADR 0007's retry/preservation infrastructure lands. The trade-off is that a single problem whose cost vastly exceeds the cap (e.g., `cap=$0.01`, problem actually spends `$1.00`) won't be killed mid-flight — the cap only prevents the *next* problem from running. Acceptable for v1; revisit when single-problem cost regularly exceeds the per-trial cap by more than ~2×.

Single warning fraction (0.8) is a v1 simplification — operators can't tune warning vs. hard-stop independently. If operators ask for asymmetric bands (warn early, halt late) the constant becomes a parameter.

**Related:** [ADR 0005 — Trial Cost and Budget Model](adrs/0005-trial-cost-and-budget.md); [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md); `python/tests/test_trial_runner.py::test_per_trial_cost_cap_*`; `python/tests/test_optimizer_driver.py::test_per_run_cost_cap_*`.
