# The Haskell DSL

The Haskell side of pi-agent-space is a *precursor* artifact. It worked out the categorical structure that the Python implementation now realizes, and continues to receive ADR-driven updates so it stays coherent with the Python. **It is not source-of-truth** — when the Haskell and the Python disagree, the Python is right (see [`ARCHITECTURE.md`](ARCHITECTURE.md)).

This document covers what's in the `haskell/` tree and how to read it. The Haskell code is meant to speak for itself; this is just orientation.

## Contents

- [Files](#files)
- [`AgentSpace.hs` — the DSL](#agentspacehs--the-dsl)
- [`Ports.hs` — the three pure ports](#portshs--the-three-pure-ports)
- [Case Studies](#case-studies)
  - [Claude Code](#claude-code)
  - [OpenClaw](#openclaw)
- [Relationship to the Math](#relationship-to-the-math)

---

## Files

- `haskell/src/AgentSpace.hs` — the agent-graph DSL: a strict monoidal GADT plus `Outcome`, `NoisyEstimate`, `paretoFrontier`, `predictPerformance`.
- `haskell/src/Ports.hs` — three pure ports (`AgentHarnessPort`, `ScoringPort`, `PackageProposerPort`).
- `haskell/src/ClaudeCodeArchitecture.hs` — speculative case study reconstructed from a March 2026 leak.
- `haskell/src/OpenClawArchitecture.hs` — real case study, mirroring the deployed OpenClaw messaging-gateway package.

---

## `AgentSpace.hs` — the DSL

`AgentSpace.hs` defines `AgentGraph` as a strict monoidal GADT: routing primitives (`Id`, `Seq`, `Par`, `Copy`, `Drop`, `Choice`, `Loop`) plus domain morphisms (`CallModel`, `ApplySkill`, `RunTests`, `MergeStrings`, …). The GADT's typed shape gives the Haskell compiler the ability to reject ill-formed agent topologies at compile time.

Two ADR commitments are pinned down here at the type level so the math and the optimizer can rely on them:

- **ADR 0007 trial outcome.** `data Outcome = Completed Metrics | BoundaryViolation Metrics | ErrorEscalated`. The optimizer's surrogate sees `Completed` and `BoundaryViolation` (the latter teaches the cost cliff in feature space); `ErrorEscalated` is preserved for asynchronous human classification and does not feed the surrogate. `metricsOf :: Outcome -> Maybe Metrics` is the projection used by `paretoFrontier`.
- **ADR 0006 heteroscedastic surrogate.** `data NoisyEstimate a = NoisyEstimate { mean :: a, variance :: a }`. `predictPerformance` returns `Either String (NoisyEstimate Metrics)` — the trial map is non-deterministic and the noise level varies with the configuration; the surrogate models both mean and input-dependent variance. The current implementation is a v1 stub returning zero variance until the real Phase 6 HetGP lands.

---

## `Ports.hs` — the three pure ports

`Ports.hs` mirrors the Python ports as a 3-port pure cut:

- `AgentHarnessPort m` — `runHarness :: Package -> GraduatedProblem -> m RawTelemetry`.
- `ScoringPort m` — `scoreObjective`, `scoreSubjective`.
- `PackageProposerPort m` — `proposeNext :: History -> m Package`.

`PersistencePort` and `EvalSuiteSourcePort` are deliberately omitted: trial storage and suite-loading are I/O at the edges, not part of the math, and they have Python homes. The 3:5 mismatch with Python is documented in `docs/terminology.md`.

The placeholder data types in `Ports.hs` (`Package`, `RawTelemetry`, `ObjectiveMetrics`, `Outcome`, `Trial`, …) carry comments noting which ADR shapes them — the file doubles as a one-page index of structural commitments.

---

## Case Studies

A useful test of the DSL's expressiveness is whether it can describe real-world agent architectures cleanly. Two case studies exercise this — one speculative, one deployed — and demonstrate that the categorical primitives chosen for the DSL (and therefore reflected in the Python's `Package` shape and the optimizer's slot space) are expressive enough to describe the architectures we care about optimizing.

### Claude Code

The Claude Code architecture coordinates a session and spawns isolated sub-agents for parallel work. In the DSL, this is the strict monoidal tensor product (`***` / `Par`) plus the `Copy` routing primitive to safely duplicate context, followed by `MergeStrings` to gather results.

```haskell
-- Forks the context to parallel sub-agents (Explore, Plan)
coordinatorSubAgents :: AgentGraph (Prompt, Context) Code
coordinatorSubAgents =
    Copy
    >>> ( (Id >>> CallModel "Claude-3-Haiku-Explore")
          ***
          (Id >>> CallModel "Claude-3-Opus-Plan")
        )
    >>> MergeStrings
```

The "Dreaming" memory-consolidation routine — taking a modified context and feeding it back into the loop — cannot be modeled by a DAG. We use a categorical **trace**, implemented in the DSL via `ArrowLoop`:

```haskell
-- The Claude Code "Dreaming" (Memory Consolidation) Loop
dreamingLoop :: AgentGraph Code TestResult
dreamingLoop = loop DreamSkill
```

Hidden features (KAIROS background daemon, Undercover metadata-stripping mode) compose as ordinary skills:

```haskell
claudeCodeWorkflow :: AgentGraph (Prompt, Context) TestResult
claudeCodeWorkflow =
    coordinatorSubAgents
    >>> ApplySkill "KAIROS_Background_Refactor"
    >>> ApplySkill "Strip_CoAuthoredBy_Metadata"
    >>> RunTests
```

The GADT's typing means the Haskell compiler proves the topological connections are well-formed (e.g., the output of the KAIROS daemon matches the required input for Undercover Mode) before any execution.

### OpenClaw

OpenClaw implements a messaging gateway by directly importing and instantiating Pi's `AgentSession` rather than spawning it as a subprocess. The embedded paradigm requires custom tool injection, dynamic system prompt construction, and parallel event subscription for streaming intermediate results.

A custom tool-policy pipeline — context-modifying operations composed sequentially:

```haskell
toolPipeline :: AgentGraph Context Context
toolPipeline =
    ApplyContextSkill "Filter_Tools_By_Policy"
    >>> ApplyContextSkill "Normalize_Tool_Schemas"
    >>> ApplyContextSkill "Enforce_Sandbox_Paths"
```

Event subscription — tapping a stream without interrupting its primary flow — is the `Copy` morphism plus a parallel tensor product, then `ExtractCode` to discard the tap's termination type:

```haskell
agentExecutionWithStreaming :: AgentGraph (Prompt, Context) Code
agentExecutionWithStreaming =
    Copy
    >>> ( CallModel "OpenClaw-Embedded-Session"
          ***
          SubscribeStream
        )
    >>> ExtractCode
```

The full workflow weaves auth resolution, tool policy, and embedded-session execution:

```haskell
openClawWorkflow :: AgentGraph (Prompt, Context) TestResult
openClawWorkflow =
    (Id *** ApplyContextSkill "Resolve_Auth_Profile")
    >>> (Id *** toolPipeline)
    >>> agentExecutionWithStreaming
    >>> RunTests
```

---

## Relationship to the Math

`docs/math.pdf` formalizes the same structure as the Haskell DSL — `AgentSpace.hs` and the math paper are two views of one categorical object. When an ADR refines the domain (ADR 0006's heteroscedastic noise model, ADR 0007's `Outcome` sum type), the Haskell types and the math paper update in lockstep so the two precursor artifacts stay coherent. See [`ARCHITECTURE.md → Precursor: The Categorical Paper`](ARCHITECTURE.md#precursor-the-categorical-paper) for what the paper covers.

---

## See Also

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the Python implementation, which is canonical.
- **[`docs/math.pdf`](../math.pdf)** — categorical formalism: monoidal structure, Pareto optimization, heteroscedastic surrogate, trial outcome sum.
- **[`haskell/`](../../haskell/)** — the source itself; the Haskell code is meant to speak for itself.
