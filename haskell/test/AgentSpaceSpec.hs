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
    it "finds the non-dominated configurations" $ do
      let m1 = Metrics { tokensConsumed = 1000, qualityScore = 0.8 }
          m2 = Metrics { tokensConsumed = 2000, qualityScore = 0.7 } -- dominated by m1
          m3 = Metrics { tokensConsumed = 1500, qualityScore = 0.9 } -- not dominated
          t1 = Trial Id m1
          t2 = Trial Id m2
          t3 = Trial Id m3
      map metrics (paretoFrontier [t1, t2, t3]) `shouldBe` [m1, m3]

  describe "Bayesian Optimization" $ do
    it "predicts performance based on history (stub)" $ do
      let m1 = Metrics { tokensConsumed = 1000, qualityScore = 0.8 }
          history = [Trial Id m1]
      predictPerformance history Copy `shouldBe` Right m1

    it "fails to predict if history is empty" $ do
      predictPerformance [] Copy `shouldBe` Left "No history to predict from"
      
    it "acquires the next configuration to test (stub)" $ do
      let history = [] :: History Prompt Prompt
      -- Just verify it returns something without erroring
      let nextGraph = acquireNextConfiguration history
      evaluateGraph nextGraph "test" `shouldReturn` Pass
