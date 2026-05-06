{-# LANGUAGE EmptyDataDecls #-}
module Ports where

-- ============================================================================
-- Ports: an experimental sketch
-- ============================================================================
--
-- This module is a candidate addition to the Haskell domain model: the five
-- ports introduced in ADR 0002 (Hexagonal Architecture for the Python
-- evaluator), expressed as records of functions parameterized by an effect
-- monad `m`.
--
-- Question this file is intended to surface: do ports belong in the Haskell?
-- The user's stated hesitation: "I use the haskell for thinking about the
-- domain, and there, the ports and adapters are an implementation detail
-- rather than integral to the domain... maybe."
--
-- The file deliberately splits the ports into two groups so that the question
-- can be answered group-by-group:
--
--   * Domain-flavored ports (AgentHarness, Scoring, PackageProposer) express
--     *interpretation choices* of the abstract semantic model — they decide
--     what an AgentGraph means in concrete execution. These have a real claim
--     on a place in the categorical model.
--
--   * IO-boundary ports (Persistence, EvalSuiteSource) are mostly side-effect
--     plumbing. If they don't earn their place, they can be retired from the
--     Haskell and live solely in Python.
--
-- See docs/terminology.md for the harness-layer and item-type vocabulary
-- (Bockeler), and docs/implementation-plan.md for the v1 R&D path that
-- consumes these ports.

-- ----------------------------------------------------------------------------
-- Placeholder types
-- ----------------------------------------------------------------------------
-- Placeholders for the broader Haskell drift backport (Package, Trial-as-
-- event-stream, EvalSuite, capability profile, objective/subjective scoring
-- split). They exist here only to make the port shapes concrete enough to
-- evaluate. Refining them is a separate change once the port shape is
-- approved.

data Package           -- user harness instance + model selection (Bockeler)
data EvalSuiteRef      -- reference to a graduated problem set
data GraduatedProblem  -- one validatable problem in a suite
data Workspace         -- materialized scratch dir for one (problem, trial)
data RawTelemetry      -- agent's raw output: events, exit code, generated artifacts
data ObjectiveMetrics  -- tokens, validation pass rate, static-analysis quality (computational scoring)
data SubjectiveScore   -- human / LLM-judge rating + notes (inferential scoring; arrives async)
data Trial             -- (package, evalSuiteRef, versionVector, events, finalScore)
data TrialEvent        -- one phase event in a trial's stream
data History           -- materialized trial history seen by the proposer

-- ============================================================================
-- Domain-flavored ports
-- ============================================================================
-- These ports correspond to choices in the abstract semantic model — they
-- pick a target interpretation for an AgentGraph. Modeling them in Haskell
-- makes the (interpretation choice) ↔ (concrete adapter) boundary visible at
-- the type level, parameterized by the effect monad `m`. The same `m`
-- threads through `runTrial` below, so the orchestration logic is pure with
-- respect to IO and only adapters specialize `m` to `IO`.

-- | Run (Pi + package) against a materialized workspace; return raw telemetry.
-- This is the boundary between abstract package definition (Bockeler's user
-- harness + model) and concrete execution. Pi (the builder harness) is
-- treated as a black box behind this port per ADR 0001.
data AgentHarnessPort m = AgentHarnessPort
  { runHarness :: Package -> GraduatedProblem -> Workspace -> m RawTelemetry
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
-- IO-boundary ports
-- ============================================================================
-- These ports concern side effects (read/write to disk). They are not
-- interpretation choices in the categorical sense, but explicit adapter
-- boundaries. Whether they belong in the Haskell at all is the open question
-- this file surfaces.

-- | Persist trials per ADR 0003 (per-trial directory, append-only events).
data PersistencePort m = PersistencePort
  { saveTrial     :: Trial -> m ()
  , appendEvent   :: Trial -> TrialEvent -> m ()
  , finalizeTrial :: Trial -> m ()
  , loadTrials    :: m [Trial]
  }

-- | Load a graduated problem set as an EvalSuite.
data EvalSuiteSourcePort m = EvalSuiteSourcePort
  { loadSuite :: EvalSuiteRef -> m [GraduatedProblem]
  }

-- ============================================================================
-- TrialRunner sketch
-- ============================================================================
-- The trial runner is generic in the effect monad `m`, depending only on the
-- ports. This is the structural payoff of the port abstraction: orchestration
-- logic is pure with respect to IO; only adapters specialize `m` to `IO`.
--
-- Body intentionally left abstract — the type signature is the artifact for
-- review. Once placeholder types are refined by the broader Haskell drift
-- backport, the body will orchestrate:
--   1. loadSuite suiteSource suiteRef
--   2. for each problem: runHarness …; scoreObjective …; appendEvent …
--   3. finalizeTrial; saveTrial

runTrial
  :: Monad m
  => AgentHarnessPort m
  -> ScoringPort m
  -> PersistencePort m
  -> EvalSuiteSourcePort m
  -> Package
  -> EvalSuiteRef
  -> m Trial
runTrial _harness _scoring _persistence _suiteSource _pkg _suiteRef = undefined
