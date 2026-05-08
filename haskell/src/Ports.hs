{-# LANGUAGE EmptyDataDecls #-}
module Ports where

-- ============================================================================
-- Ports: the domain-flavored cut
-- ============================================================================
--
-- This module models the three ports that express *interpretation choices* of
-- the abstract semantic model — the parameters that turn an AgentGraph into a
-- concrete execution. They are records of functions parameterized by an
-- effect monad `m`; the same `m` threads through `runTrial` so that
-- orchestration logic stays pure with respect to IO and only adapters
-- specialize `m` to `IO`.
--
-- Two ports from the Python side are deliberately omitted from the Haskell:
--
--   * PersistencePort — trial storage (per ADR 0003) is side-effect plumbing,
--     not part of the math. Persisting a Trial value is Python's concern.
--
--   * EvalSuiteSourcePort — loading a graduated problem set from disk is IO
--     at the edges; once loaded, the suite is just data. `runTrial` therefore
--     takes `[GraduatedProblem]` as a parameter, not a port.
--
-- The math claim ("the Haskell is a reification of the categorical model")
-- is preserved by this cut. The legibility cost of the 3:5 mismatch with
-- Python is paid in docs/terminology.md, where the Bockeler-axis flavor of
-- each port is documented and the IO-boundary concerns are pointed at their
-- Python homes. The five-port variant lives on the `exploration/haskell-
-- ports-with-io` branch for reference.
--
-- See docs/terminology.md for the harness-layer and item-type vocabulary
-- (Bockeler), and docs/implementation-plan.md for the v1 R&D path.

-- ----------------------------------------------------------------------------
-- Placeholder types
-- ----------------------------------------------------------------------------
-- Placeholders for the broader Haskell drift backport (Package as user
-- harness + model; Trial as event stream; capability profile; objective/
-- subjective scoring split). They exist here only to make the port shapes
-- concrete enough to evaluate.

data Package           -- user harness instance + model selection (Bockeler)
data GraduatedProblem  -- one validatable problem in a suite
data RawTelemetry      -- agent's raw output: events, exit code, generated artifacts
data ObjectiveMetrics  -- tokens, dollars, validation pass rate, quality (computational scoring; ADR 0005 splits cost into tokens + dollars). Per ADR 0006 the (config, problem) -> ObjectiveMetrics map is non-deterministic with input-dependent variance, modeled by a heteroscedastic GP.
data SubjectiveScore   -- human / LLM-judge rating + notes (inferential scoring; arrives async)
data Outcome           -- ADR 0007 sum: Completed ObjectiveMetrics | BoundaryViolation ObjectiveMetrics | ErrorEscalated. The optimizer's surrogate sees the Completed and BoundaryViolation projections; ErrorEscalated trials are preserved for asynchronous human classification.
data Trial             -- (package, problems, versionVector, events, outcome :: Outcome)
data History           -- materialized trial history seen by the proposer

-- ============================================================================
-- Domain-flavored ports
-- ============================================================================

-- | Run (Pi + package) against a problem; return raw telemetry.
-- This is the boundary between abstract package definition (Bockeler's user
-- harness + model) and concrete execution. Pi (the builder harness) is
-- treated as a black box behind this port per ADR 0001. Workspace
-- materialization is an internal concern of the adapter, not part of the
-- math.
data AgentHarnessPort m = AgentHarnessPort
  { runHarness :: Package -> GraduatedProblem -> m RawTelemetry
  }

-- | Map raw telemetry → objective metrics (computational scoring), and
-- ingest async subjective scores (inferential scoring; typically partial,
-- arrives after the trial closes). The two-method split mirrors Bockeler's
-- computational/inferential distinction at the scoring layer.
data ScoringPort m = ScoringPort
  { scoreObjective  :: RawTelemetry -> m ObjectiveMetrics
  , scoreSubjective :: Trial -> m (Maybe SubjectiveScore)
  }

-- | Propose the next package given trial history. Domain-relevant because
-- the proposer's logic IS the optimizer (Phase 3 random-from-slot-space;
-- Phase 6 surrogate-driven). Also where the substitution principle
-- (inferential → computational, when semantics-preserving) lives as a
-- known-dominant-move catalog.
data PackageProposerPort m = PackageProposerPort
  { proposeNext :: History -> m Package
  }

-- ============================================================================
-- TrialRunner sketch
-- ============================================================================
-- The trial runner is generic in the effect monad `m`, depending only on the
-- domain ports plus the (already-loaded) suite as data. Persistence happens
-- in Python after `runTrial` returns the Trial value.
--
-- Body intentionally left abstract — the type signature is the artifact for
-- review. Once placeholder types are refined by the broader Haskell drift
-- backport, the body will orchestrate, for each problem in the suite:
--   1. runHarness package problem
--   2. scoreObjective rawTelemetry
--   3. record per-problem events into the growing Trial
-- and return the final Trial value. Subjective scoring lands later (async)
-- and updates the trial outside `runTrial`.

runTrial
  :: Monad m
  => AgentHarnessPort m
  -> ScoringPort m
  -> Package
  -> [GraduatedProblem]
  -> m Trial
runTrial _harness _scoring _pkg _problems = undefined
