module AgentSpaceSpec (spec) where

import Test.Hspec
import AgentSpace
import Control.Category ((>>>))
import Control.Arrow ((***), (+++), loop)

spec :: Spec
spec = do
  describe "AgentSpace DSL" $ do
    it "evaluates Id to the same input" $ do
      evaluateGraph Id "hello" `shouldReturn` "hello"
      
    it "evaluates sequential composition of Id and a skill" $ do
      let graph = Seq Id (ApplySkill "uppercase")
      evaluateGraph graph "hello" `shouldReturn` "HELLO"

    it "supports Category >>> operator" $ do
      let graph = ApplySkill "uppercase" >>> Id
      evaluateGraph graph "hello" `shouldReturn` "HELLO"

    it "supports Arrow *** operator for parallel composition" $ do
      let graph = ApplySkill "uppercase" *** ApplySkill "uppercase"
      evaluateGraph graph ("hello", "world") `shouldReturn` ("HELLO", "WORLD")

    it "supports ArrowChoice +++ operator for conditional routing" $ do
      let graph = ApplySkill "uppercase" +++ ApplySkill "uppercase"
      evaluateGraph graph (Left "hello") `shouldReturn` Left "HELLO"
      evaluateGraph graph (Right "world") `shouldReturn` Right "WORLD"

    it "supports Copy for duplicating streams" $ do
      evaluateGraph Copy "hello" `shouldReturn` ("hello", "hello")

    it "supports Drop for discarding streams" $ do
      evaluateGraph Drop "hello" `shouldReturn` ()

    it "supports ArrowLoop for feedback traces" $ do
      let graph = loop (Par Id Id) -- A trivial loop that passes data through
      evaluateGraph graph "loop_test" `shouldReturn` "loop_test"

    it "evaluates standardPiAgent end-to-end" $ do
      let standardPiAgent = 
            Copy 
            >>> (Id *** QueryMCP "github-pr-server")
            >>> CallModel "claude-3-7-sonnet"
            >>> ApplySkill "linter-skill"
            >>> RunTests
      
      evaluateGraph standardPiAgent "Implement binary search" `shouldReturn` Pass

    it "supports parameterized morphisms (ParaGraph)" $ do
      let params = ModelParams { temperature = 0.7 }
          paraGraph = Para (CallParameterizedModel "claude-3-7-sonnet")
      evaluatePara paraGraph params ("test_prompt", ["ctx"]) `shouldReturn` "Code from claude-3-7-sonnet at temp 0.7"

  describe "Pareto Optimization" $ do
    it "finds the non-dominated configurations (3D: tokens, dollars, quality)" $ do
      let m1 = mkMetrics 1000 0.001 0.8 -- on frontier
          m2 = mkMetrics 2000 0.002 0.7 -- dominated by m1 on all axes
          m3 = mkMetrics 1500 0.003 0.9 -- on frontier (best quality)
          t1 = Trial Id (Completed m1)
          t2 = Trial Id (Completed m2)
          t3 = Trial Id (Completed m3)
      map (metricsOf . outcome) (paretoFrontier [t1, t2, t3]) `shouldBe` [Just m1, Just m3]

    it "keeps tokens-cheap-but-dollar-expensive on the frontier alongside its mirror" $ do
      -- ADR 0005: tokens and dollars are independent axes. Per the
      -- mixed-squad motivating scenario, the operator's limiting
      -- factor varies — both configurations are useful and neither
      -- dominates the other.
      let mTokenCheap  = mkMetrics 100  0.05  0.7 -- low tokens, high dollars
          mDollarCheap = mkMetrics 1000 0.005 0.7 -- high tokens, low dollars
          tA = Trial Id (Completed mTokenCheap)
          tB = Trial Id (Completed mDollarCheap)
      length (paretoFrontier [tA, tB]) `shouldBe` 2

    it "dominates a boundary-violated trial that loses on every axis" $ do
      -- Boundary-violated trials carry zeroed quality per ADR 0007's
      -- C1 rule, so a completed trial that's also cheaper than the
      -- boundary trial dominates it on all axes and pushes it off
      -- the frontier. (Boundary trials remain first-class data for
      -- the surrogate — see ADR 0006 — but the frontier UX filters
      -- them out when stronger completed trials exist.)
      let mGood     = mkMetrics 500  0.001 0.9
          mBoundary = mkMetrics 5000 0.05  0.0
          tGood     = Trial Id (Completed mGood)
          tBoundary = Trial Id (BoundaryViolation mBoundary)
      map (metricsOf . outcome) (paretoFrontier [tGood, tBoundary])
        `shouldBe` [Just mGood]

    it "keeps a boundary-violated trial on the frontier when nothing dominates it" $ do
      -- A cheap-but-zero-quality boundary trial and an expensive-but-
      -- high-quality completed trial are mutually non-dominating:
      -- the boundary wins on cost, the completed wins on quality.
      -- Both should appear on the frontier so the Phase 6 surrogate
      -- sees the boundary as cliff signal in feature space.
      let mBoundaryCheap = mkMetrics 100  0.001 0.0
          mExpensive     = mkMetrics 5000 0.05  0.9
          tBoundary      = Trial Id (BoundaryViolation mBoundaryCheap)
          tCompleted     = Trial Id (Completed mExpensive)
      length (paretoFrontier [tBoundary, tCompleted]) `shouldBe` 2

    it "excludes error-escalated trials from the frontier (ADR 0007)" $ do
      let m1 = mkMetrics 1000 0.001 0.8
          tCompleted = Trial Id (Completed m1)
          tError = Trial Id ErrorEscalated
      map (metricsOf . outcome) (paretoFrontier [tCompleted, tError]) `shouldBe` [Just m1]

  describe "Bayesian Optimization" $ do
    it "predicts performance with a noisy estimate (stub)" $ do
      let m1 = mkMetrics 1000 0.001 0.8
          zeroVar = Metrics
              { tokensConsumed     = 0
              , costDollars        = 0
              , validationPassRate = 0
              , qualityScore       = 0
              }
          history = [Trial Id (Completed m1)]
      predictPerformance history Copy `shouldBe`
        Right NoisyEstimate { mean = m1, variance = zeroVar }

    it "fails to predict if history is empty" $ do
      predictPerformance [] Copy `shouldBe` Left "No history to predict from"

    it "skips error-escalated history when predicting" $ do
      let history = [Trial Id ErrorEscalated]
      predictPerformance history Copy `shouldBe`
        Left "Most recent trial has no metrics (error-escalated)"

    it "acquires the next configuration to test (stub)" $ do
      let history = [] :: History Prompt Prompt
      -- Just verify it returns something without erroring
      let nextGraph = acquireNextConfiguration history
      evaluateGraph nextGraph "test" `shouldReturn` Pass

-- | Helper: build a Metrics with validationPassRate == qualityScore,
-- matching the v1 SyntheticSuiteScorer convention. Tests that only
-- need the three frontier axes use this to stay legible.
mkMetrics :: Int -> Float -> Float -> Metrics
mkMetrics t d q = Metrics
    { tokensConsumed     = t
    , costDollars        = d
    , validationPassRate = q
    , qualityScore       = q
    }
