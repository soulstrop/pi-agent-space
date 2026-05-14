# pi-agent-space

The elements that influence an AI agent's performance—foundation models of varying sizes and lineages, specialized skills, complex workflows, and diverse training protocols—are advancing at a breakneck pace. Keeping up with these delivered innovations and trying to figure out what yields better performance often means dealing with an overwhelming combinatorial explosion. Standard benchmarks exist, but there isn't necessarily a way to relate them directly to a developer's specific problem domain.

**pi-agent-space** is a system designed to efficiently and systematically explore this multidimensional space. By treating the "builder harness" (the Pi platform) and the "user harness" (the package of skills, prompts, and models) as a composed system, this project optimizes the agent's behavior against a graduated problem suite. It finds configurations on the Pareto frontier of trade-offs, like tokens used, dollars spent, scaling slope across problem difficulties, and overall quality.

## Supported Scenarios

This shared exploration space is designed to support three core deployment scenarios:

1. **The Individual Developer (Ad Hoc):** A developer hears about a new model or tool and wants to quickly try it out. They need fast A/B testing (in minutes) to get a feel for whether it's an improvement or just noise, and to understand the shape of the trade-offs.
2. **Strategic Pre-Exploration (Deep-Pocketed Organization):** An organization explores the massive combinatorial space upfront before large-scale rollout. Operating under a budget cap, the goal is to find the "golden" configuration and build a persistent knowledge asset (a surrogate model) that maps out the cost-quality frontier.
3. **Evolutionary Fleet Management (Large Organization):** A mature deployment runs experiments with slight variations on packages through regular updates. By gathering multimodal online feedback (user ratings, derived metrics, and "golden" signals like signed contracts), the system establishes an organizational feedback loop that steadily increases agent performance over time, eventually evolving toward segmented, highly-personalized packages.

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

**Current Stage:** We have successfully closed out **Phase 3** (tagged `phase-3-complete`). On top of Phase 2's single-trial end-to-end pipeline (real Pi execution via `CliSubprocessAdapter`, per-trial-directory persistence, real scoring), Phase 3 lands:

*   A slot/value space schema (`SlotSpace`) with Bockeler-tagged candidate values per slot.
*   A `RandomFromSlotSpace` proposer that dedups against trial history by candidate-identity hash.
*   A 3D Pareto frontier over `(tokens_consumed, cost_dollars, quality_score)` per ADR 0005 — tokens and dollars stay as independent axes because token-cheap models can be dollar-expensive across providers.
*   A multi-trial `OptimizerDriver` loop with per-trial + per-run cost-cap enforcement (ADR 0005, two-threshold watchdog), a consecutive-errors / time-without-completed-trial circuit breaker (ADR 0007), and adapter-layer retry budget with exponential backoff (ADR 0007 B1).
*   A driver-mechanics acceptance test (`test_acceptance_phase3.py`) verified end-to-end against real Pi.

**What's Next:** Before starting Phase 4, a small **Step 3.5.1 cleanup** addresses three findings from the Phase 3 retrospective (predicate de-duplication, problem-id filter, declarative `retry_budget` doc — see [`docs/implementation-plan.md`](docs/implementation-plan.md)). Five **open spikes** (ADRs 0008–0012) are queued against their target phases.

Then **Phase 4 (Capability profile and scaling slope)** brings:

*   A multi-difficulty graduated problem suite (`002_*`, `003_*`).
*   Per-(problem, metric) events with `(value, n_samples)` payloads, enabling replicates > 1 (ADR 0006).
*   Capability-profile aggregation: `(mean, variance, p95, scaling_slope)` per metric.
*   The 4D Pareto frontier — `(mean_tokens, mean_dollars, scaling_slope, mean_quality)`.

Later phases add async subjective scoring (Phase 5) and a Heteroscedastic GP surrogate driving Bayesian acquisition (Phase 6).

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
