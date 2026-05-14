{-# LANGUAGE EmptyDataDecls #-}
module Ports where

import AgentSpace (Metrics)
-- ^ Re-use the categorical-layer types whose shape is load-bearing.
-- 'Metrics' carries the 4-axis objective record committed by ADR 0005;
-- 'Outcome' (also in AgentSpace) is the sum type from math.pdf eq. 6
-- and ADR 0007. Re-declaring either here would be silent drift.

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
-- Placeholder types — IO-edge / domain-record concerns below the math
-- ----------------------------------------------------------------------------
-- These are empty data declarations on purpose. They sit below the
-- categorical abstraction this DSL exercises: the math.pdf framework treats
-- @Package@ as an opaque parameter @p@ in @Para(C)@, @RawTelemetry@ as an
-- adapter-specific artifact, @GraduatedProblem@ as IO-loaded data, etc.
-- Fleshing them into Python-mirroring records adds no categorical content
-- and risks Python-Haskell drift; structural verification of these records
-- lives in Python per ADR 0001.
--
-- Types whose shape DOES matter to the math live in AgentSpace.hs and are
-- imported above: 'Metrics' (the 4D objective-metrics record per ADR 0005)
-- and 'Outcome' (the sum type per math.pdf eq. 6 / ADR 0007). Re-declaring
-- either here would be drift; the alias below preserves the descriptive
-- 'ObjectiveMetrics' name in port signatures without duplicating structure.

data Package           -- user harness instance + model selection (Bockeler)
data GraduatedProblem  -- one validatable problem in a suite
data RawTelemetry      -- agent's raw output: events, exit code, generated artifacts
data SubjectiveScore   -- human / LLM-judge rating + notes (inferential scoring; arrives async)
data Trial             -- domain-level trial record (package, problems, versionVector, events, outcome). Broader than AgentSpace.Trial, which carries only (config, outcome) for the categorical layer.
data History           -- materialized trial history seen by the proposer

-- | ObjectiveMetrics keeps the descriptive name in port signatures and
-- reuses the categorical 'Metrics' structure. The (config, problem) →
-- ObjectiveMetrics map is non-deterministic per ADR 0006 with input-
-- dependent variance, modeled by a heteroscedastic GP.
type ObjectiveMetrics = Metrics

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
