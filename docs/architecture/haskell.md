# The Haskell DSL

The Haskell side of pi-agent-space is a *precursor* artifact. It worked out the categorical structure that the Python implementation now realizes, and continues to receive ADR-driven updates so it stays coherent with the Python. **It is not source-of-truth** — when the Haskell and the Python disagree, the Python is right (see [`ARCHITECTURE.md`](ARCHITECTURE.md)).

This document covers what's in the `haskell/` tree and how to read it. The Haskell code is meant to speak for itself; this is just orientation.

## Contents

- [Files](#files)
- [`AgentSpace.hs` — the DSL](#agentspace.hs-the-dsl)
- [`Ports.hs` — the three pure ports](#ports.hs-the-three-pure-ports)
- [Case Studies](#case-studies)
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

A useful test of the DSL's expressiveness is whether it can describe real-world agent architectures cleanly. Two case studies exercise this:

- **Claude Code** (`haskell/src/ClaudeCodeArchitecture.hs`) — speculative reconstruction from a March 2026 leak. Demonstrates parallel sub-agents via `Par`/`Copy`/`MergeStrings`, "Dreaming" memory consolidation as a categorical trace via `ArrowLoop`, and hidden features (KAIROS, Undercover) as composed skills.
- **OpenClaw** (`haskell/src/OpenClawArchitecture.hs`) — real, deployed messaging-gateway package. Demonstrates embedded `AgentSession` instantiation, a tool-policy pipeline of `ApplyContextSkill` morphisms, and event-stream tapping via `Copy` + parallel tensor product.

The full walkthroughs — diagrams, code, categorical commentary — live in [`modeling-external-architectures.md`](modeling-external-architectures.md). They are not ports of these systems into pi-agent-space; they are evidence that the categorical primitives in the DSL (and therefore reflected in the Python's `Package` shape and the optimizer's slot space) are expressive enough to describe the architectures we care about optimizing.

> **Forward note.** When the Python implementation supports it (a richer slot-space schema, multi-role packages, the mixed-squad workflows of ADR 0005), the case studies should be moved out of the Haskell precursor and into the Python — expressed as actual `Package` configurations the optimizer can run. Their current home in Haskell reflects where the design started, not where it should end up.

---

## Relationship to the Math

`docs/math.pdf` formalizes the same structure as the Haskell DSL — `AgentSpace.hs` and the math paper are two views of one categorical object. When an ADR refines the domain (ADR 0006's heteroscedastic noise model, ADR 0007's `Outcome` sum type), the Haskell types and the math paper update in lockstep so the two precursor artifacts stay coherent. See [`ARCHITECTURE.md → Precursor: The Categorical Paper`](ARCHITECTURE.md#precursor-the-categorical-paper) for what the paper covers.

---

## See Also

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the Python implementation, which is canonical.
- **[`modeling-external-architectures.md`](modeling-external-architectures.md)** — full walkthroughs of the Claude Code and OpenClaw case studies.
- **[`docs/math.pdf`](../math.pdf)** — categorical formalism: monoidal structure, Pareto optimization, heteroscedastic surrogate, trial outcome sum.
- **[`haskell/`](../../haskell/)** — the source itself; the Haskell code is meant to speak for itself.
