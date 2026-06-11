# Title: 0023 - Configuration Registry and Startup Validation

**Status:** Accepted

## Context

Operational parameters that govern an optimization run are currently scattered
across constructor signatures and module-level constants in three layers:

| Parameter | Today's home | Layer |
| --- | --- | --- |
| `per_trial_cost_cap_usd`, `per_run_cost_cap_usd` | `OptimizerDriver.__init__`, `TrialRunner.run_trial` | orchestration |
| `COST_CAP_WARNING_FRACTION = 0.8` | module constant in `trial_runner.py` | orchestration |
| `max_consecutive_errors`, `max_time_without_completed_trial` | `OptimizerDriver.__init__` | orchestration |
| `bootstrap_threshold` | `OptimizerDriver.__init__` | orchestration |
| `retry_budget` (declarative), | `OptimizerDriver.__init__` | orchestration |
| `retry_budget` (effective), `backoff_seconds` | `CliSubprocessAdapter.__init__` | adapter |
| `DEFAULT_RETRY_BACKOFF_SECONDS = (30.0, 60.0)`, `RETRY_JITTER_RANGE = (0.5, 1.5)` | module constants in `cli_subprocess_adapter.py` | adapter |

This raises three coupled problems, tracked as `pi-agent-space-44u`
(no central registry), `pi-agent-space-gfm` (no startup validation), and
`pi-agent-space-7pr` (magic numbers in production logic):

1. **No single typed source of truth.** An operator who wants to know "what
   knobs exist and what are their defaults" must read three files. There is no
   one place that enumerates, types, and documents the operational surface.

2. **Some knobs are not tunable without a code edit.** The warning fraction
   (`0.8`), the retry backoff schedule (`(30.0, 60.0)`), and the jitter range
   (`(0.5, 1.5)`) are hardcoded module constants. Changing them per-environment
   requires editing source.

3. **No startup validation.** Nothing verifies — before a run begins — that a
   provider API key is present or that the configured values are coherent
   (non-negative caps, warning fraction in range). A misconfigured unattended
   run fails late and confusingly (e.g. every trial `error_escalated` because no
   key was set) instead of aborting immediately with a clear message.

### Constraints from the existing design record

- **Hexagonal purity (CLAUDE.local.md §4).** The domain layer is pure data with
  no I/O. Reading environment variables *is* I/O, so a settings object that
  reads `os.environ` cannot live in `domain/`. The current injection pattern —
  every parameter passed explicitly into a constructor — is correct hexagonal
  style and must be preserved.

- **No upward dependencies.** Domain and adapters must not import a config
  singleton. If they did, the registry would become an ambient global that the
  inner layers depend on, inverting the dependency arrows. The registry must be
  read at the composition root and its values passed *down* into constructors —
  the same way values are passed today, just sourced from one object.

- **Stdlib-first precedent.** ADR-adjacent design note *"pi-eval score CLI:
  argparse, direct adapter, no port"* rejected Click because "argparse is
  stdlib; adding [a dependency] for [this] is not justified by v1 scope."
  `pyproject.toml` further minimizes dependency weight (CPU-only torch pin). The
  `pi-agent-space-44u` note *suggests* Pydantic Settings, but that conflicts
  with this precedent and is treated here as a suggestion, not a constraint.

- **Relationship to `RunConfig` (ADR 0013).** `domain/types.py` already has a
  frozen `RunConfig` written to `run_config.json` per run. That is a
  **point-in-time snapshot** of the parameters that governed *one* run, for
  post-hoc reconstruction. It is **not** the operational source-of-truth and is
  not env-aware. The registry introduced here is the *source* that feeds those
  values; `RunConfig` remains the *persisted record*. They must not be merged:
  one reads the environment and validates, the other is pure persisted data.

### The `gfm` startup gap

`OptimizerDriver` is currently constructed only in tests — there is no
`mise run optimize`, no optimizer CLI, and no production composition root. The
only entry point that exists is `pi-eval score`. So "validate at application
startup" has no startup to attach to yet. This ADR therefore defines validation
as a **first-class function on the registry**, exercised by tests and intended
to be called by the composition root when the optimizer entry point lands —
rather than coupling validation to a CLI that does not exist (the optimizer CLI
is separate future work).

## Options Considered

### Registry implementation

1. **Stdlib frozen dataclass + explicit `from_env` / `validate`.** A
   `@dataclass(frozen=True) Settings` in an edge-layer module, with a
   `from_env(env=os.environ)` classmethod and a `validate()` method.
   - *Pros:* zero new dependencies; matches the argparse-not-Click precedent;
     `from_env` and `validate` are explicit and trivially testable by passing a
     fake env dict; frozen-ness gives immutability for free.
   - *Cons:* env parsing (string → `float | None`, tuple parsing) is hand-rolled
     rather than declarative.

2. **Pydantic Settings (`pydantic-settings`).** Declarative env binding +
   validation + typing.
   - *Pros:* less hand-rolled parsing/validation; rich error messages.
   - *Cons:* a new runtime dependency against the stdlib-first precedent; pulls
     validation semantics into a third-party DSL; heavier than the v1 surface
     (≈8 scalar knobs) warrants.

### Where the registry lives

1. **A new edge module `pi_evaluator/config.py`** (sibling to
   `logging_config.py`, which is the existing precedent for an edge-layer
   cross-cutting concern). Read at the composition root, passed down.
2. **In `domain/`** — rejected: violates hexagonal purity (env I/O in the
   domain) and would invite the upward-dependency antipattern.

### How validation reaches a startup

1. **Reusable `Settings.validate()`, defer the optimizer CLI** — validation is a
   method exercised by tests now and called by the future composition root.
2. **Build a minimal `pi-eval optimize` CLI in this slice** — rejected for now:
   expands the trio into building the optimizer entry point, which is its own
   piece of work.

## Decision

**1. Registry implementation: stdlib frozen dataclass.** Introduce
`pi_evaluator/config.py` with a frozen `Settings` dataclass that enumerates the
operational knobs with their current values as defaults:

- `per_trial_cost_cap_usd: float | None = None`
- `per_run_cost_cap_usd: float | None = None`
- `cost_cap_warning_fraction: float = 0.8` (was `COST_CAP_WARNING_FRACTION`)
- `retry_budget: int = 2`
- `retry_backoff_seconds: tuple[float, ...] = (30.0, 60.0)` (was `DEFAULT_RETRY_BACKOFF_SECONDS`)
- `retry_jitter_range: tuple[float, float] = (0.5, 1.5)` (was `RETRY_JITTER_RANGE`)
- `max_consecutive_errors: int | None = None`
- `max_time_without_completed_trial: timedelta | None = None`
- `bootstrap_threshold: int = 10`

`Settings.from_env(env=os.environ)` builds an instance from `PI_EVAL_`-prefixed
environment variables, falling back to the dataclass defaults when a variable is
absent. The `env` parameter is injectable so tests pass a fake dict and never
touch the real process environment.

**2. Placement: an edge-layer module, not the domain.** `config.py` sits beside
`logging_config.py`. Domain and adapters are **not** modified to import it; they
keep their current constructor parameters. The composition root (the future
optimizer entry point) reads `Settings`, then constructs `CliSubprocessAdapter`,
`TrialRunner`, and `OptimizerDriver` by passing the relevant fields down — the
dependency arrows stay pointed inward. The module-level constants
(`COST_CAP_WARNING_FRACTION`, `DEFAULT_RETRY_BACKOFF_SECONDS`,
`RETRY_JITTER_RANGE`) are removed from their current homes once `Settings`
carries the defaults; the few in-`src` references are updated to take the value
from the injected parameter rather than the module global. (`COST_CAP_WARNING_FRACTION`
is currently imported by `optimizer_driver.py` from `trial_runner.py`; that
import is replaced by the injected `cost_cap_warning_fraction` value.)

**3. Validation: a reusable `Settings.validate()`.** `validate()` raises a
single `ConfigError` (a new exception type in `config.py`) with a clear,
actionable message when configuration is incoherent or unusable:

- **At least one provider API key present** — `GEMINI_API_KEY`,
  `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` (the three the acceptance suite
  selects from; `GOOGLE_API_KEY` is an alternate that does not select a model on
  its own, per `.env.example`). Absence of all three is a hard error: an
  unattended run with no key produces only `error_escalated` trials.
- **`cost_cap_warning_fraction` in `(0.0, 1.0]`.**
- **Cost caps, if set, are positive** (`> 0`); `None` (no cap) stays valid.
- **`retry_budget >= 0`**, **`bootstrap_threshold >= 0`**.
- **`retry_backoff_seconds` non-empty with all values `>= 0`**;
  **`retry_jitter_range` is `(low, high)` with `0 <= low <= high`.**

The API-key check reads the environment, so it lives in `validate()` (the
I/O-aware edge), not in the dataclass construction. `validate()` is exercised
directly by unit tests now; the optimizer CLI/composition root will call
`Settings.from_env().validate()` at startup when it lands. Building that CLI is
out of scope for this ADR.

**4. `RunConfig` is unchanged.** It remains the per-run persisted snapshot
(ADR 0013). The composition root populates it from the same `Settings` values it
uses to build the driver, but the two types stay distinct: `Settings` is the
env-aware, validated source-of-truth; `RunConfig` is the immutable record.

## Reconsider Triggers

- **The knob count or parsing complexity grows** (nested config, per-role
  overrides, file-based config layered over env) to where hand-rolled parsing is
  error-prone — revisit Pydantic Settings or `tomllib`-backed file config.
- **A real optimizer CLI / composition root lands** and wants config from
  multiple sources (env + flags + file) with a precedence policy — that
  precedence belongs in a follow-up note or ADR amendment.
- **A provider beyond the current three** becomes selectable and the API-key
  presence check needs to widen (keep it in lockstep with `.env.example` and the
  sandbox env allowlist in `adapters/sandbox.py`).
- **`retry_budget` stops being declarative-only on the driver** (ADR 0007 /
  design-note follow-up) — the registry already carries one value; wiring it
  through removes the driver/adapter duplication.

## Consequences

- New module `python/src/pi_evaluator/config.py` (`Settings`, `ConfigError`,
  `from_env`, `validate`). No `__init__.py` (PEP 420 namespace packages).
- `COST_CAP_WARNING_FRACTION`, `DEFAULT_RETRY_BACKOFF_SECONDS`, and
  `RETRY_JITTER_RANGE` are removed as module constants; their values become
  `Settings` field defaults. In-`src` references switch to injected parameters.
  This is a **Doc-Sync trigger**: the design notes *"Cost-cap enforcement…"* and
  *"Adapter-layer retries…"* name these constants and must be updated in the
  same commit (or an immediate sibling) when they move.
- Constructor signatures change only **additively**, and every existing
  parameter keeps its current default — so every existing call site (including
  all current tests) keeps working unchanged. The registry is a new *source* for
  these arguments, not a replacement for the injection seam. Two of the lifted
  constants are today **inline module globals, not parameters** — making them
  env-tunable (the point of `pi-agent-space-7pr`) requires promoting them to
  defaulted constructor parameters:
  - `CliSubprocessAdapter`: new `retry_jitter_range: tuple[float, float] =
    (0.5, 1.5)` (was the inline `RETRY_JITTER_RANGE`); `backoff_seconds`'s
    default literal absorbs `DEFAULT_RETRY_BACKOFF_SECONDS`.
  - `TrialRunner` and `OptimizerDriver`: new `cost_cap_warning_fraction: float =
    0.8` (was the inline `COST_CAP_WARNING_FRACTION`, imported across both). This
    stays a **single** symmetric fraction — it does not split warn/halt into two
    bands (that remains the design-note's future trigger); it only relocates the
    one knob from a code constant to an env-tunable parameter.
- **Defaults are intentionally duplicated** between each component's signature
  and the matching `Settings` field: the component default is the "no registry"
  fallback, the `Settings` default is the "from env" fallback, and they must
  agree. A unit test in `test_config.py` asserts they coincide, guarding drift
  (the test layer may import both freely; this does not create an `src`-level
  upward dependency on the registry).
- No production composition root is added in this slice; `validate()` is dead
  code in `src` until the optimizer entry point calls it, but it is live in
  tests. This is intentional and noted as future work.
- No new runtime dependency.

## Future optimize CLI surface (non-binding notes)

These are observations gathered while scoping `gfm` — *not* decisions this ADR
commits to. They record what we now know the eventual composition root will need
to look like, so the next person doesn't re-derive it. The optimizer CLI is
separate future work (likely its own issue/ADR); capture, don't commit.

- **Shape mirrors `pi-eval score`.** A new `pi-eval optimize` subcommand in
  `pi_evaluator/cli/` (argparse, direct adapter wiring, no port, PEP 420 — same
  recipe as the score-CLI design note). Adding a *second* subcommand is itself
  the trigger that note flagged ("revisit Click at Phase 6 if multi-subcommand
  complexity warrants it") — re-evaluate argparse-vs-Click when `optimize`
  lands, though two subcommands alone likely still favor stdlib.
- **It is the composition root and the `gfm` call site.** First action at
  startup: `Settings.from_env().validate()` — aborting on `ConfigError` before
  any provider call or workspace materialization. This is the live caller that
  retires the "`validate()` is dead code in `src`" consequence above.
- **What it assembles** (reading fields off the validated `Settings`):
  `CliSubprocessAdapter(retry_budget, backoff_seconds, …)` →
  `TrialRunner(cost_cap_warning_fraction, …)` → proposer + `PerTrialDirectoryAdapter`
  persistence → `OptimizerDriver(per_trial/per_run caps, max_consecutive_errors,
  max_time_without_completed_trial, bootstrap_threshold, …)`, then
  `driver.run(trial_budget)`. It also builds the `RunConfig` snapshot from the
  same `Settings` values (the two stay distinct per the Decision).
- **Runtime inputs that are *not* `Settings` fields.** `trial_budget`,
  `eval_suite_ref`, and the slot space are per-invocation arguments (CLI flags /
  files), not operational config — they describe *this run's* task, not the
  environment. `trial_budget` is the most natural required flag; `Settings`
  governs *how* trials run, the flags govern *what* run to do. Keep that line
  crisp so the two config surfaces don't bleed together.
- **Config precedence is unresolved.** If the CLI grows explicit flags that
  overlap `Settings` (e.g. `--per-trial-cost-cap`), it needs a documented
  precedence (flag > env > default is the conventional choice). Deferred — see
  the matching Reconsider Trigger; this ADR only defines env → defaults.
- **Provider/model selection echoes the acceptance suite.** `.env.example`
  already encodes "first provider whose key is set picks that provider's cheap
  model." The optimize CLI's default slot space / model enumeration should reuse
  that same precedence so `validate()`'s key check and the CLI's model choice
  never disagree.
- **`mise run optimize`.** ADR 0005 refers to caps as "per `mise run optimize`
  invocation," implying a root mise task will front the CLI — the unattended
  entry point operators actually invoke.

## Related

- [ADR 0005 — Trial Cost and Budget Model](0005-trial-cost-and-budget.md) (cost caps, two-threshold warning policy)
- [ADR 0007 — Pi Invocation Lifecycle](0007-pi-invocation-lifecycle.md) (retry budget, circuit breaker)
- [ADR 0013 — Driver-run event log](0013-driver-run-event-log.md) (`RunConfig` snapshot)
- `docs/design-notes.md` — *"Cost-cap enforcement: between-step polling, single warning fraction"*, *"Adapter-layer retries: inside the adapter, default budget=2"* (Doc-Sync targets)
- Issues `pi-agent-space-44u`, `pi-agent-space-gfm`, `pi-agent-space-7pr`
- `pi-agent-space-2gf` — the optimizer composition-root CLI that will call
  `Settings.from_env().validate()` at startup (see *Future optimize CLI surface*)
