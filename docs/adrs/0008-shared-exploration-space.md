# Title: 0008 - Shared Exploration Space and Scenario Pivot

**Status:** Draft

## Context

The landscape of agentic elements—foundation models of varying sizes and lineages, specialized skills, complex workflows, and diverse training protocols—is expanding at a breakneck pace. For developers, this creates a combinatorial explosion: identifying which innovations yield real performance improvements versus noise is overwhelming without a systematic way to relate standard benchmarks to specific problem domains.

`pi-agent-space` provides the engine to explore this multidimensional space. Through a deep-dive analysis, we identified three primary deployment patterns that the system must support:

1.  **Individual Developer Ad Hoc:** Rapid A/B testing (sub-10 minute feedback) to "get a feel" for a new model or tool.
2.  **Strategic Pre-Exploration (Deep-Pockets):** Large-scale, budget-capped optimization to find a "golden" configuration before high-volume rollout.
3.  **Evolutionary Fleet Management (Large Organization):** Continuous online improvement through live A/B experimentation against production traffic, evolving toward segmented (personalized) optimization.

The common value across all three is the **Shared Exploration Space**: the cumulative knowledge of what works, under what conditions, regardless of whether the trial was run by a developer on a laptop or a fleet in production.

## Decision

To support this vision and the rapid transition from ad hoc R&D to fleet-scale management, we are pivoting the implementation plan to prioritize foundational robustness over purely sequential module builds.

**1. Pull forward Parallelism and Sampling (Phase 1/2 Core).** 
To meet the "minutes-to-results" requirement for individual developers (Scenario 1), the core `TrialRunner` will natively support parallel trial execution and automated problem sampling. This provides the speed needed for ad hoc work and the throughput needed for strategic exploration (Scenario 2).

**2. Metadata-Rich Evaluation Suites (Phase 1 Domain types).**
To support the future goal of segmented optimization (Scenario 3) without overcomplicating the v1 surrogate, we are adding optional metadata tags (e.g., `target_segment`, `task_category`) to the `GraduatedProblem` and `EvalSuiteRef` schemas. These tags serve as proxies for context, allowing the "shared exploration space" to categorize insights by segment from the beginning.

**3. Queue-Mediated Filesystem Persistence.**
Instead of pivoting to a multi-writer SQL backend, we will maintain the easily legible, filesystem-based mapping of the solution space. To support multiple concurrent writers across different deployment scenarios (e.g., batch runs, live fleet updates), we will introduce a queue to mediate updates to the shared knowledge space. Because these scenarios are unlikely to produce conflicting updates, the queue worker can rely on a simple "last write wins" resolution strategy.

**4. Persistent Surrogate as Knowledge Asset.**
The surrogate model is promoted from a transient optimization tool to a first-class project asset. The system will support serializing and versioning the surrogate alongside the trial history so it can be "warm-started" or queried for sensitivity analysis across related domains.

## Consequences

- **Implementation Plan Update:** Phases 1 and 2 are modified to include parallelism and sampling.
- **Domain Type Change:** `Package`, `Trial`, and `GraduatedProblem` receive metadata fields for segment/task tagging.
- **Persistence Architecture:** We retain filesystem-based persistence but will introduce an update queue and a worker process to handle concurrent writes safely.
- **Surrogate Featurization:** The featurization logic in Phase 6 will incorporate the metadata tags, enabling implicit segmented optimization.
- **Performance:** Sub-10 minute feedback for Scenario 1 becomes a core design constraint.

## Reconsider Triggers

- **Update Clashes:** If the "last write wins" strategy leads to unacceptable data loss or instability as concurrent writes scale up.
- **Filesystem Bottlenecks:** If filesystem IO bounds the throughput of the queue worker under enterprise loads, we may need to reconsider a database backend.
- **Scaling costs:** If parallel execution on real Pi exceeds user budgets too quickly for Scenario 1, we may need more aggressive early-exit or sampling heuristics.
