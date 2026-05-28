# Agent Instructions: pi-agent-space

Welcome. This is the primary instruction manual for AI coding assistants working on `pi-agent-space`. Read this file to understand the project's unique constraints, architecture, and workflows.

**CRITICAL MANDATE: NEVER use TodoWrite, TaskCreate, or markdown TODO lists. Use `bd` (beads) for ALL task tracking.**

## 1. Quick Reference & Core Directives

*   **Source of Truth:** The Python implementation (`python/src/pi_evaluator/`) is the canonical source of truth. The categorical paper (`docs/math.pdf`) and Haskell DSL (`haskell/`) are precursors.
*   **Tooling:** `mise` is the universal task runner. `uv` manages
    Python. `ty` is the type checker (ignore Pyright errors).  Repo is
    organized as a monorep0, with mise.toml at the root, in the python
    and haskell subdirectopries.  The root mise.toml uses subidrectory
    mise tasks as appropriate, e.g. './mise run test' calls
    './haskell/mise run test' and './python/mise run test'
*   **Architecture:** Hexagonal (ports-and-adapters). Domain at the center, ports as protocols, adapters at the edges, orchestration on top. No upward dependencies.
*   **Issue Tracking:** (`docs/implementation-plan.md`) describes the overarching design and sequence of the work, while beads manages the active state, assignment, and lifecycle of those work items. `bd` (beads).
*   **Non-Interactive Shell:** ALWAYS use non-interactive flags (e.g., `cp -f`, `rm -rf`) to avoid hanging the agent loop.

## 2. Issue Tracking: Beads (MANDATORY)

This project strictly uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Workflow

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
```

### Session Completion Protocol

When ending a work session, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

1.  **File issues:** Create issues for anything that needs follow-up.
2.  **Run quality gates:** `mise run test`, `mise run lint`, `mise run typecheck`.
3.  **Update status:** Close finished work (`bd close <id>`), update in-progress items.
4.  **PUSH TO REMOTE (MANDATORY):**
    ```bash
    git pull --rebase
    git push
    git status  # MUST show "up to date with origin"
    ```
5.  **Clean up:** Clear stashes, prune remote branches.
6.  **Verify:** All changes committed AND pushed.
7.  **Hand off:** Provide context for the next session.

**CRITICAL:** NEVER stop before pushing. NEVER say "ready to push when you are" - YOU must push. If push fails, resolve and retry.

### Persistent Knowledge

Use `bd remember` for persistent knowledge. Do NOT use `MEMORY.md` files.

## 3. Development Workflow

### Setup

```bash
mise run setup
```
*(Idempotent; runs `uv sync` in the `python/` directory).*

### Running Tests

The full suite runs Python + Haskell:

```bash
mise run test
```

**Fast Dev Loop (Python Only):**

```bash
cd python
mise run test 
```

**Smoke Test (Crucial for CI/CD checks):**
Validates the optimizer pipeline without the real `pi` binary or API keys. Run this after modifying `TrialRunner`, ports, or adapters.

```bash
cd python
uv run python ../.claude/skills/run-pi-agent-space/smoke.py
```

### Linting & Typechecking

```bash
mise run lint       # ruff
mise run typecheck  # ty (Trust this over Pyright)
```

### Acceptance Tests (Real Pi)

Acceptance tests require the `pi` binary on `PATH` and an API key (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`).

```bash
cd python
mise run test-acceptance-full   # production-default budget (~7-8 min per trial)
```
*(Note: `test-acceptance-fast` is currently a placeholder and will fail if no tests are tagged).*

## 4. Architecture & Domain

### Hexagonal Layers

1.  **Domain (`pi_evaluator/domain/`):** Pure data. Frozen dataclasses (`Package`, `RawTelemetry`, `Metrics`). `Trial` is mutable. No I/O.
2.  **Ports (`pi_evaluator/ports/`):** `typing.Protocol` definitions (`AgentHarnessPort`, `ScoringPort`, `PersistencePort`, `EvalSuiteSourcePort`).
3.  **Adapters (`pi_evaluator/adapters/`):** Concrete implementations (e.g., `CliSubprocessAdapter`, `SyntheticSuiteScorer`).
4.  **Orchestration (`pi_evaluator/trial_runner.py`):** `TrialRunner` composes ports into the pipeline: `configured → (eval, scored_objective)+ → finalized`.

### Key Concepts

*   **Package:** The variable being optimized (`model`, `system_prompt`, `skills`, `template_values`).
*   **Trial Outcomes:** `completed`, `boundary_violation` (hit cost/time cap), `error_escalated`.
*   **Persistence (ADR 0003):** 4-file layout per trial (`config.json`, `versions.json`, `events.jsonl`, `final.json`).

## 5. Gotchas & Known Issues

*   **Pyright:** Ignore Pyright "could not be resolved" diagnostics. They are noise. Trust `mise run typecheck` (`ty`).
*   **Namespace Packages:** Do NOT create `__init__.py` files anywhere under `python/src/pi_evaluator/`. The project uses PEP 420 namespace packages. Adding `__init__.py` breaks editable installs.
*   **Haskell Tests:** `mise run test` is Haskell-dominated (~28s cold
    compile). For fast Python iteration, use `cd python && mise run test`.
*   **Bwrap Integration Tests:** On Linux, `BwrapSandbox` integration tests may skip if user namespaces are disabled. On macOS, they skip permanently. This is expected behavior.

## 6. Development Methodology

*   **TDD Red-Green-Refactor:**
    1.  **Red:** Write a failing test for a small behavioral expectation.
    2.  **Green:** Write minimal code to pass.
    3.  **Refactor:** Restructure for clarity while keeping tests green.
*   **Vertical Slices:** Each phase delivers an end-to-end working pipeline at current fidelity, not isolated modules.
*   **Commit Strategy:** Prefer small, frequent commits that leave the suite green.
*   **Doc-Sync Gate:** If a commit deletes or renames a symbol referenced in `docs/` (design notes, implementation plan), ADRs, or `REVIEW.md`, you MUST update those references in the same or an immediate sibling commit.
*   **Interface Reviews:** Surface port shapes and schema gaps at phase boundaries before proceeding to the next phase.
