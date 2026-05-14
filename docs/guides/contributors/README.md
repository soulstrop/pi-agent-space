# Contributors Guide

Setup, workflows, and conventions for contributing to pi-agent-space.

## Getting Started

1. **Tooling.** We use [`mise`](https://mise.jdx.dev/) as the task runner and tool manager. The Python environment is managed via `uv` / `hatchling`.
2. **Set up the workspace:**
   ```bash
   mise run setup
   ```
3. **Run tests, lint, format, typecheck** from the repository root:
   ```bash
   mise run test
   mise run lint
   mise run format
   mise run typecheck
   ```
   *(You can also run Python-specific tasks directly, like `mise run test-python`).*

## Running the full test suite

The Python suite includes two bwrap-backed integration tests in `python/tests/test_sandbox.py` that exercise the real `BwrapSandbox` recipe end-to-end. They gracefully skip (via a functional `bwrap_available()` probe) when bwrap can't actually create a sandbox on the host.

On Linux contributor workstations — especially Ubuntu 24.04+ — bwrap is installed but blocked by default from creating user namespaces. The integration tests will skip until that's resolved. See the [operators guide § Trial isolation](../operators/README.md#trial-isolation-enabling-bwrapsandbox-on-a-linux-host) for the setup steps; Family 1.B (targeted AppArmor profile) is the recommended path.

After completing setup, the full suite should run with zero skips. The bwrap integration tests are required only for full-suite green; the argv-shape unit tests in the same file cover the sandbox contract without needing bwrap to actually execute.

On macOS, `BwrapSandbox` cannot run at all and its integration tests skip permanently. This is the documented Linux/macOS dev-loop divergence ([ADR 0009](../../adrs/0009-trial-isolation-boundary.md)).

## TDD Workflow

This project is heavily driven by Test-Driven Development and organized into independent, verifiable steps. When picking up a step from [`docs/implementation-plan.md`](../../implementation-plan.md), follow the Red-Green-Refactor cadence: write a failing test first, make it pass with minimal code, then refactor for clarity.

## Documentation conventions

Before making structural changes, check [`docs/adrs/`](../../adrs/) or [`docs/implementation-plan.md`](../../implementation-plan.md) to ensure alignment with the architectural direction. Significant decisions go into ADRs (see [`docs/adrs/README.md`](../../adrs/README.md) for the status lifecycle and spike workflow). Smaller design choices that don't warrant an ADR go into [`docs/design-notes.md`](../../design-notes.md) — promote a design note to an ADR when it accumulates consequences.

## Where to go next

For a deeper technical overview of the domain types and adapter boundaries, start with [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md). The Python source layout (ports, adapters, domain) under `python/src/pi_evaluator/` mirrors the hexagonal architecture described there.
