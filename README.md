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

**Current Stage:** Phases 1–5 are complete. The system runs end-to-end against real Pi, accumulates trials with a 5D Pareto frontier, and accepts out-of-band subjective scores.

**Phase 4 (Capability profile and scaling slope)** delivered:

*   A multi-difficulty graduated problem suite and per-`(problem, metric)` event recording.
*   Capability-profile aggregation: `(mean, variance, p95, scaling_slope)` per metric.
*   The **4D Pareto frontier** — `(mean_tokens, mean_dollars, scaling_slope, mean_quality)`.
*   Acceptance test verifying that a poorly-scaling configuration is distinguished by `scaling_slope`.

**Phase 5 (Subjective scoring, async and partial)** delivered:

*   A `subjective.json` sidecar written by `pi-eval score <trial-id> <rating>` (ADR 0014). `final.json` is objective-only and never mutated after a trial closes.
*   Partial-score policy (ADR 0015): missing subjective scores are excluded from dependent axes rather than blocking the optimizer.
*   The **5D Pareto frontier** — objective 4D axes plus the subjective axis. Trials without a subjective score participate in the 4D objective axes but are excluded from subjective-axis dominance comparisons.
*   Acceptance tests covering the transition from an objective-only frontier to a fully-scored one.
*   Structured JSON logging (ADR 0015) and a `Run` first-class domain entity (ADR 0013).
*   Conventional commit enforcement (`committed`) and changelog generation (`git-cliff`) with a pre-push hook.

**What's Next:** **Phase 6 (Surrogate model and acquisition)** replaces random search with a Heteroscedastic GP surrogate that directs proposals toward Pareto-improving configurations via expected hypervolume improvement. See [`docs/implementation-plan.md`](docs/implementation-plan.md) for the step-by-step plan.

## Contributing

We welcome contributions! Setup, test workflows, TDD conventions, and pointers to the technical architecture are in the [contributors guide](docs/guides/contributors/README.md). Operators deploying or running trials should start from the [operators guide](docs/guides/operators/README.md).

Real-Pi trials and the acceptance suite need at least one model-provider API key (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`); copy [`.env.example`](.env.example) to `.env` and see the [contributors guide § Getting Started](docs/guides/contributors/README.md#getting-started) for details. The unit suite and smoke harness need no keys.
