# pi-agent-space

**pi-agent-space** is a Bayesian combinatorial-optimization system that searches for high-performing **packages** — bundles of skills, prompts, workflows, foundation-model selections, and configuration values that plug into Pi's extension surface.

By treating the "builder harness" (Pi) and the "user harness" (the package) as a composed system, this project optimizes the agent's behavior against a graduated problem suite to find configurations on the Pareto frontier of trade-offs like tokens used, dollars spent, scaling slope across problem difficulties, and overall quality.

## Project Structure

The project has a few important directories you should know about:

*   **`python/` (The Source of Truth)**
    The core implementation lives here, specifically in `python/src/pi_evaluator/`. It uses a hexagonal (ports-and-adapters) architecture, splitting concerns into domain logic, interfaces (ports), concrete implementations (adapters), and an orchestration layer (`TrialRunner`). **When in doubt, the Python implementation is what the optimizer actually does.**
*   **`docs/`**
    Contains the project's foundational theory and decision records. 
    *   `docs/architecture/` holds architecture documentation, including `ARCHITECTURE.md` (a deep dive into the system structure).
    *   `docs/math.pdf` is the categorical precursor paper formalizing the system's mathematics.
    *   `docs/adrs/` contains Architecture Decision Records (ADRs) tracking significant design choices.
    *   `docs/implementation-plan.md` defines the phased, TDD-driven roadmap.
*   **`graduated_problems/`**
    The suite of problems (e.g., `001_binary_search`) used to evaluate how well a given agent package performs.
*   **`haskell/`**
    A precursor Haskell Domain-Specific Language (DSL) used as a rigorous thinking and modeling tool.

## Current Status and What's Next

The project is currently structured around a phased implementation plan. 

**Current Stage:** We have successfully closed out **Phase 2**. We now have a single-trial end-to-end pipeline with real Pi execution (`CliSubprocessAdapter`), real persistence (`PerTrialDirectoryAdapter`), and real scoring over materialized workspaces.

**What's Next:** The focus is now on **Phase 3 (Multi-config search, random proposer, basic Pareto)**. This phase will introduce:
*   A slot/value space schema to generate multiple package configurations.
*   A random proposer to select novel configurations from the slot space.
*   A multi-trial optimizer loop that enforces cost and retry bounds.
*   The first multi-dimensional Pareto frontier computation (e.g., tokens vs. dollars vs. quality).
*   Later phases (Phase 4+) will introduce multi-difficulty capability profiles and eventually a Heteroscedastic Gaussian Process surrogate model for Bayesian acquisition (Phase 6).

## Contributing

We welcome contributions! This project is heavily driven by **Test-Driven Development (TDD)** and is organized in independent, verifiable steps. 

### Getting Started

1.  **Tooling:** We use [`mise`](https://mise.jdx.dev/) as our task runner and tool manager. The Python environment is managed via `uv` / `hatchling`.
2.  **Setup the workspace:** 
    ```bash
    mise run setup
    ```
3.  **Run tests and checks:**
    You can run tests, linting, and formatting from the repository root:
    ```bash
    mise run test
    mise run lint
    mise run format
    mise run typecheck
    ```
    *(You can also run Python-specific tasks directly, like `mise run test-python`).*
4.  **TDD Workflow:** When picking up a step from `docs/implementation-plan.md`, always follow the Red-Green-Refactor cadence. Write a failing test first, make it pass with minimal code, and then refactor for clarity.
5.  **Documentation:** Before making structural changes, check `docs/adrs/` or `docs/implementation-plan.md` to ensure alignment with the architectural direction.

For a deeper technical overview of the domain types and adapter boundaries, start by reading [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).
