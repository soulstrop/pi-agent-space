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

**Where:** `python/src/pi_evaluator/trial_runner.py` (`_classify_outcome`); `python/src/pi_evaluator/lifecycle.py` (`is_model_error`).

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

**Decision:** Cost-cap enforcement is **between-step polling**, not a parallel watchdog: the per-trial cap is checked after each problem's `metric_record` events have been emitted inside `TrialRunner.run_trial` (per ADR 0012; previously `scored_objective`); the per-run cap is checked after each trial completes inside `OptimizerDriver.run`. The "two thresholds" commitment from ADR 0005 is realized as a single configurable hard cap (`per_trial_cost_cap_usd`, `per_run_cost_cap_usd`) plus a fixed warning fraction `COST_CAP_WARNING_FRACTION = 0.8` of that cap. Warning events for per-trial caps land in the trial event stream as `cost_cap_warning` (phase) with `scope="per_trial"`; per-run warnings are emitted via Python `logging.warning` on the driver's logger rather than as trial events, because they cross trial boundaries and the trial-event invariant is *"`finalized` is the last event"*.

The between-step approach was chosen over a parallel signal-handling watchdog for v1 because Pi runs are short relative to step granularity, the harness is `subprocess.run` not a streaming reader, and intra-step kill (SIGTERM/SIGKILL of a running Pi) carries cleanup hazards (half-mutated workspace, partial event stream) that we'd rather not engage with until ADR 0007's retry/preservation infrastructure lands. The trade-off is that a single problem whose cost vastly exceeds the cap (e.g., `cap=$0.01`, problem actually spends `$1.00`) won't be killed mid-flight — the cap only prevents the *next* problem from running. Acceptable for v1; revisit when single-problem cost regularly exceeds the per-trial cap by more than ~2×.

Single warning fraction (0.8) is a v1 simplification — operators can't tune warning vs. hard-stop independently. If operators ask for asymmetric bands (warn early, halt late) the constant becomes a parameter.

**Related:** [ADR 0005 — Trial Cost and Budget Model](adrs/0005-trial-cost-and-budget.md); [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md); `python/tests/test_trial_runner.py::test_per_trial_cost_cap_*`; `python/tests/test_optimizer_driver.py::test_per_run_cost_cap_*`.

---

### Circuit breaker: boundary_violations are neutral, completed resets, monotonic clock

**Where:** `python/src/pi_evaluator/optimizer_driver.py` (`run` circuit-breaker checks; `monotonic_clock` parameter).

**Decision:** The driver's circuit breaker (ADR 0007) tracks two state machines between trials. (1) A `consecutive_errors` counter that **increments only on `error_escalated`**, **resets only on `completed`**, and is **left unchanged on `boundary_violation`** — a boundary-violated trial neither breaks an error streak nor counts as one. Trips when the counter is `>= max_consecutive_errors`. (2) A `last_completed_at` wall-clock timestamp from a monotonic clock that advances only when a trial finishes with `outcome=="completed"`; trips when `now - last_completed_at` exceeds `max_time_without_completed_trial.total_seconds()`.

The state transitions are driven by Bockeler-style symmetry: `completed` is the *positive* signal that resets both state machines; `error_escalated` is the *operationally suspicious* signal that the breaker exists to catch; `boundary_violation` is a *useful negative signal* (ADR 0006 — the HetGP learns the cost cliff from it) and so does not contribute to "the optimization isn't making progress." A run of pure boundary_violations does not trip the error breaker but will eventually trip the time breaker once `max_time_without_completed_trial` elapses without any `completed` trial — which is the correct behavior.

The driver takes a `monotonic_clock` callable (default `time.monotonic`) so tests can advance the clock deterministically. Wall-clock measurement uses `time.monotonic` rather than `datetime.now()` to be NTP-correction-safe.

The trip-condition order in the loop is: error breaker → time breaker → per-run cost cap. Ordering is observable only in the rare case where two thresholds cross on the same trial; the listed order reports the "earlier-conceptually" reason first (errors are loudest).

**Related:** [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md); `python/tests/test_optimizer_driver.py::test_circuit_breaker_*`.

---

### Adapter-layer retries: inside the adapter, default budget=2

**Where:** `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py` (`CliSubprocessAdapter.run`); `python/src/pi_evaluator/lifecycle.py` (`is_model_error`).

**Decision:** ADR 0007 B1's retry budget is implemented **inside `CliSubprocessAdapter`** rather than as a wrapping decorator port, so the "same materialized workspace across retries" commitment is honored natively (the workspace is created once per `run` call before the retry loop, not per attempt). The adapter takes `retry_budget` (default `2`, meaning up to 2 retries on top of the initial attempt = 3 total attempts), `backoff_seconds` (default `(30.0, 60.0)`), and an injectable `sleep` callable so tests don't actually wait. Retryable signals are evaluated by `lifecycle.is_model_error` — non-zero subprocess exit OR an assistant `message_end` with `stopReason == "error"`. Step 3.5.1 (commit `2611d45`) extracted this predicate to a shared module so the orchestrator's `_classify_outcome` and the adapter's retry loop cannot drift; the earlier duplication (one copy per call site) was retired then.

The driver-level `retry_budget` parameter (`OptimizerDriver.__init__`) is **declarative-only in v1** (commit `cfa9f53`). The driver stores the value but does not plumb it into the harness; operators wire the budget at `CliSubprocessAdapter` construction time. Resolution (remove the param or wire it through) defers to v2 — tracked under "What's deferred" in `docs/implementation-plan.md`.

When `retry_budget` exhausts without success, the adapter returns the last attempt's `RawTelemetry` verbatim. The trial runner's `_classify_outcome` rule sees this and tags the trial `error_escalated`, satisfying ADR 0007's "persistent errors preserve and queue" commitment (the trial directory is already on disk, so preservation is automatic — a dedicated preservation queue is not part of this chunk). Tests that intentionally exercise failure paths must opt out with `retry_budget=0` to avoid 90-second real-time backoff waits; the production-quality default (2 retries, 30/60s backoff) is what unattended runs need.

**Related:** [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md); `python/tests/test_cli_subprocess_adapter.py::test_retries_*`, `test_default_retry_budget_is_two`, `test_returns_last_failure_after_retry_budget_exhausted`, `test_retries_use_same_materialized_workspace`.

---

### Trial isolation: SandboxPort, NullSandbox default, BwrapSandbox opt-in

**Where:** `python/src/pi_evaluator/ports/sandbox_port.py`; `python/src/pi_evaluator/adapters/sandbox.py`; `python/src/pi_evaluator/adapters/cli_subprocess_adapter.py` (`__init__` `sandbox` parameter; `_run_once` invocation routing).

**Decision:** Isolation is a port (`SandboxPort.wrap(cmd, workspace, env) -> SandboxedInvocation`) rather than a hard-coded mechanism inside the adapter. `CliSubprocessAdapter`'s default is `NullSandbox` (identity), so Phase 1–3 behavior is preserved at every existing call site. `BwrapSandbox` is the v1 real-isolation implementation; the same port shape will admit a container implementation when Phase 4+ deployment scenarios force the question (ADR 0009).

The bwrap recipe deliberately **omits `--unshare-user`**. Ubuntu 24.04+ kernels default to `kernel.apparmor_restrict_unprivileged_userns=1`, which blocks bwrap's user-namespace setup even when only filesystem isolation is requested — the entire sandbox fails with `bwrap: setting up uid map: Permission denied`. The threats ADR 0009 addresses (measurement integrity, credential exposure, resource bounds) do not require uid-mapping protection; dropping the flag preserves the rest of the recipe under hardened kernels. Filesystem confinement, env scrubbing, and pid/ipc/uts/cgroup namespacing all still apply.

The env allowlist is **explicit and short** (`PATH`, `LANG`, `LC_ALL`, `TERM`, `TZ`, four well-known model API key names, `PI_*` prefix). `HOME` is **not** on the allowlist; instead, `BwrapSandbox` sets `HOME=/tmp/home` inside the sandbox and mounts a tmpfs there. This is the load-bearing safety property: the real home directory is never bind-mounted, so `~/.ssh`, `~/.aws`, `~/.config/gh`, and dotfiles holding tokens are simply unreachable. New provider keys (e.g., `MISTRAL_API_KEY`) require an explicit constructor argument — opt-in by name rather than blanket forwarding.

`bwrap_available()` is a **functional** probe, not a binary-presence check: it runs `bwrap --ro-bind /usr /usr /bin/true` and returns True only if that exits cleanly. The integration tests in `test_sandbox.py` skip via this probe so AppArmor-restricted hosts get clean skips rather than confusing failures.

**Validation steps are not sandboxed in v1.** Per ADR 0004, graduated-problem validation commands are trusted code from the project's own repo. They execute *after* the trial, against workspace contents the agent may have written — so validation tooling running over agent-authored files (e.g., `pytest` on an agent-created test) is a real but secondary risk. Sandboxing validation forces extra decisions (shell semantics across binds, validation needing non-workspace paths) and is deferred until evidence of exploitation, not speculation.

**Related:** [ADR 0009 — Trial Isolation Boundary](adrs/0009-trial-isolation-boundary.md); [ADR 0004 — Workspace Isolation](adrs/0004-workspace-isolation.md); `python/tests/test_sandbox.py`.

---

### Persistent-error preservation queue: derive-don't-store v1

**Where:** `python/src/pi_evaluator/trial_runner.py` (`run_trial` finalize path; outcome written to `final.json`); `python/src/pi_evaluator/adapters/per_trial_directory_adapter.py` (`load_trials`); future scanner helper.

**Decision:** ADR 0007 B1 commits to *preserving* trials whose retry budget exhausts and *queueing* them for asynchronous human classification. v1 satisfies both commitments without writing a new artifact at trial-finalization time. Preservation is already automatic — each trial's directory (`config.json`, `versions.json`, `events.jsonl`, `final.json`) lands on disk through `PerTrialDirectoryAdapter` during the normal trial lifecycle, and `final.json` carries `outcome="error_escalated"` for the trials in question. The "queue" is a *derived view* over that data, surfaced via a small helper that filters `PersistencePort.load_trials()` by outcome — implementation-side, a one-liner.

This decision follows ADR 0011's event-stream-as-SoT logic: the trial directory is the single durable record; any aggregated view is derived from it. Writing a separate `preservation_queue.jsonl` at finalize time would commit to a schema for review-state tracking (which trials have been reviewed, dismissed, re-queued) before any consumer of that state exists. We have no review UX, no `bd`-style triage tool, no scheduled job — the v1 need is simply "find the error_escalated trials so a human can look at them," which the scanner satisfies fully.

The scanner does not live behind a port. Outcome-filtering is not a domain operation that warrants port-shaped surface area; it is a one-time consumer-side concern. The natural shape is a free function or a `staticmethod` taking a `PersistencePort`, kept private to whatever consumer needs it (initially a CLI command or a notebook; no consumer exists in v1).

**Trade-off considered: scanner vs. event log.** Spike 0009 (driver-run event log) is open and may eventually carry per-trial outcome events at driver scope. If 0009 lands first, the preservation queue naturally moves from "scan trial directories" to "scan the driver event log" — same derive-don't-store discipline, different source. The scanner approach does not paint us into a corner here; it just gets replaced by a different derivation when a better source exists.

**Trade-off considered: review-state tracking.** A future CLI (`pi-eval triage`, `pi-eval review`, or similar) that lets operators mark trials reviewed/dismissed/re-queued *will* need durable state. That state belongs in a separate file owned by that CLI — `trials/review_state.jsonl` or similar — without touching the trial directories themselves. Adding the state surface is a v2 concern; v1 has no consumer for it.

**Trade-off considered: scaling.** Scanning `trials/*/final.json` is O(N) in trial count. At v1's expected scale (≤100 trials per run during R&D), scan time is negligible. At enterprise scale (10k+ trials), the scan would want indexing or a different persistence backend — both already documented as ADR 0003 reconsider triggers, so this isn't a new failure mode.

**Related:** [ADR 0007 — Pi Invocation Lifecycle](adrs/0007-pi-invocation-lifecycle.md) (B1 preservation commitment); [ADR 0011 — Outcome Classifier as Single Source of Truth](adrs/0011-outcome-classifier-single-source-of-truth.md) (the derive-don't-store discipline this note inherits); `docs/implementation-plan.md` "Open spikes" (0009 driver-run event log as potential successor source); issue `pi-agent-space-1da`.
