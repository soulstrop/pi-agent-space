# Terminology

This document is the canonical reference for the project's domain language. When a term is used loosely elsewhere, it should either be tightened against this glossary or this glossary should be updated.

---

## Harness layers (Bockeler)

Following Birgitta Bockeler's [Harness Engineering](https://martinfowler.com/articles/harness-engineering.html), we model an AI coding agent as three concentric circles:

| Layer | What it is | In pi-agent-space |
| --- | --- | --- |
| **Model** | The LLM at the core; "the ultimate thing being harnessed." | A *slot* in the package — the foundation-model selection. |
| **Builder harness** | What the coding-agent's builders put around the model: system prompts, retrieval mechanisms, orchestration, "even a sophisticated orchestration system." | **Pi**, treated as a black box per ADR 0001. |
| **User harness** | "Built specifically for our use case and system." | The rest of the package — guides + sensors that customize Pi for a domain. |

**pi-agent-space straddles two layers:**
- The **packages** it produces *are* user-harness instances (with a model selection at their core).
- Its **optimization infrastructure** (eval suite, trial machinery, BO loop) is meta-tooling that *helps users assemble* user harnesses. Structurally it acts like builder-harness scaffolding for the act of choosing user-harness items.

When the word *harness* appears in our docs/code, qualify it: builder harness (Pi), user harness (the package), or meta-builder-harness (the optimizer infrastructure).

---

## User-harness items: guides and sensors

A user harness comprises two regulation mechanisms, each item being one or the other:

- **Guides (feedforward).** "Anticipate behavior and steer the agent before it acts. Guides increase the probability that the agent creates good results in the first attempt."
  Examples: AGENTS.md, bootstrap scripts, CodeMod tools, performance requirements docs, logging standards, functional specs, system-prompt fragments, retrieval skills.
- **Sensors (feedback).** "Observe after the agent acts and help it self-correct."
  Examples: pre-commit hooks, ArchUnit constraint rules, test suites with coverage tracking, mutation testing, performance tests, AI code-review agents.

The model itself is *neither* a guide nor a sensor — it's the thing being harnessed.

---

## User-harness items: computational and inferential

Cross-cutting the role split, every user-harness item has a **type**:

- **Computational items.** "Deterministic and fast, run by the CPU. Tests, linters, type checkers, structural analysis. Run in milliseconds to seconds; results are reliable."
  Examples: linters, type checkers, ArchUnit, eslint, coverage tools, dep-cruiser, mutation testing.
- **Inferential items.** "Semantic analysis, AI code review, 'LLM as judge'. Typically run by a GPU or NPU. Slower and more expensive; results are more non-deterministic."
  Examples: custom linter messages used for self-correction, LLM-as-judge code reviewers, detailed architectural-review skills.

This gives a 2×2 classification:

|              | Guide (feedforward) | Sensor (feedback) |
| --- | --- | --- |
| **Computational** | structured spec, JSON schema, lint config, system-prompt rules | pre-commit hook, type checker run, test suite, ArchUnit |
| **Inferential**   | retrieval-augmented context, "review against patterns" skill | LLM-as-judge reviewer, semantic dup detector, AI architectural review |

### Substitution principle

Bockeler: *"Computational guides increase the probability of good results with deterministic tooling. Computational sensors are cheap and fast enough to run on every change, alongside the agent."* Inferential controls are reserved for problems deterministic tooling cannot address.

For pi-agent-space optimization: an **inferential→computational substitution that preserves semantics is a strictly Pareto-dominant move** — lower cost, lower latency, higher reliability — better on every axis simultaneously. The optimizer should treat known-equivalent substitutions as priority moves rather than discovering them by random sampling.

---

## Package

A **package** is a configuration that, when combined with Pi (the builder harness), produces a running agent for a specific use case. It comprises:

1. A **model** selection (the foundation model — Bockeler's center circle).
2. A **user harness**: a collection of guides and sensors plugged into Pi's extension surface (skills, prompts, workflows, MCP servers, configuration values, template values).

Each user-harness item carries both a `role` (guide / sensor) and a `type` (computational / inferential).

---

## Trial

A **trial** is a single round of evaluation: `(package, eval-suite-reference, version-vector)` exercised through the phases of the trial event stream — `configuration → evaluation → objective scoring → subjective scoring → final score`. Trials are content-addressable by candidate-change identity for dedup.

Subjective scoring is, by Bockeler's classification, **inferential** (a human or an LLM-as-judge produces it); objective scoring is typically **computational**. Partial scoring is first-class — the optimizer may proceed with only some of the three score values.

---

## Eval suite

An **eval suite** defines the validation context for a problem domain. It's domain-specific:
- For coding: a graduated set of `GraduatedProblem`s with `validation_steps` (shell commands + expected exit codes).
- For non-coding domains (e.g., insurance): a per-domain scorer and a curated reference set; the schema generalization is a placeholder ADR (see deferred items in `implementation-plan.md`).

In all three deployment scenarios, the eval suite plays the role Bockeler's user-harness sensors play locally — it produces feedback signal — but at a meta level, applied to the *choice* of package rather than to a single agent action.

---

## Capability profile

Trial-level metrics aren't scalars — they are **fibered over difficulty**. A capability profile is a function `difficulty → metric_vector`, with summary axes (mean, variance, p95, scaling slope, n_samples) computed lazily for comparison. The Pareto frontier in v1 lives in `(mean_tokens, mean_dollars, scaling_slope, mean_quality)` over capability profiles (ADR 0005 / ADR 0012), not in a 2D `(cost, quality)` collapse. Phase 5 adds a subjective axis; Phase 6 fits a heteroscedastic GP over the same axes.

---

## Ports (architectural)

Pi-agent-space's Python production code is organized as ports and adapters per ADR 0002. The five ports — documented in `implementation-plan.md` — split usefully along Bockeler's lines:

| Port | Bockeler-axis flavor |
| --- | --- |
| `AgentHarnessPort` | The boundary to the builder harness (Pi). |
| `ScoringPort` | Splits computational scoring (objective) from inferential scoring (subjective). |
| `PackageProposerPort` | Where the substitution principle lives as a known-dominant-move catalog. |
| `PersistencePort` | Pure IO plumbing, not Bockeler-flavored. |
| `EvalSuiteSourcePort` | IO plumbing with a domain wrapper. |

Whether ports belong in the Haskell domain model is an open design question (see `haskell/src/Ports.hs` for an experimental sketch).

---

## Cross-reference to memory

| Term | Canonical source |
| --- | --- |
| Model, builder harness, user harness | `project_harness_layers` |
| Guide, sensor | `project_harness_layers` |
| Computational, inferential | `project_inference_vs_computation` |
| Substitution principle | `project_inference_vs_computation` |
| Package | `project_pi_and_packages` |
| Trial event stream | `project_trial_event_stream` |
| Capability profile, scaling slope | `implementation-plan.md` Phase 4 |
| Candidate-change identity | `project_trial_event_stream` |
| Three deployment scenarios | `project_deployment_scenarios`; `user-journeys.md` |

---

## Categorical Mappings

For contributors transitioning from the mathematical precursors (`docs/math.pdf`, `AgentSpace.hs`), these are the canonical mappings:

| Domain Term | Categorical Term | Implementation |
| --- | --- | --- |
| **Agentic Step / Skill** | Morphism ($f: X \to Y$) | `ApplySkill`, `CallModel` |
| **User Harness** | Parametric Lens ($Para$) | `ParaGraph` in Haskell |
| **Trial Outcome** | Coproduct / Sum Type ($\amalg$) | `Outcome` in Python/Haskell |
| **Metric Extraction** | Projection ($\pi$) | `metricsOf` / `_has_metrics` |
| **Workflow** | Composition / Monoidal Category | `Seq` (`>>>`), `Par` (`***`) |
| **Feedback Loop** | Categorical Trace / Loop | `ArrowLoop` / `loop` |
| **Optimization Goal** | Pareto Frontier | `pareto_frontier` |
| **Surrogate Model** | Heteroscedastic GP | `NoisyEstimate` (ADR 0006) |
