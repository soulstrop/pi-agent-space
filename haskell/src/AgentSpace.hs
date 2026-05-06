{-# LANGUAGE GADTs #-}

module AgentSpace where

import Prelude hiding (id, (.))
import Control.Category
import Control.Arrow
import Data.Char (toUpper)

type Prompt  = String
type Context = [String]
type Code    = String
data TestResult = Pass | Fail String deriving (Show, Eq)

data Metrics = Metrics 
    { tokensConsumed :: Int
    , qualityScore   :: Float
    } deriving (Show, Eq)

data Trial a b = Trial 
    { config  :: AgentGraph a b
    , metrics :: Metrics
    }

paretoFrontier :: [Trial a b] -> [Trial a b]
paretoFrontier trials = 
    [ t | t <- trials, not (isDominated t trials) ]
  where
    isDominated t ts = any (\other -> 
        (tokensConsumed (metrics other) <= tokensConsumed (metrics t)) &&
        (qualityScore (metrics other) >= qualityScore (metrics t)) &&
        (metrics other /= metrics t)) ts

type History a b = [Trial a b]
type Expected a = Either String a

predictPerformance :: History a b -> AgentGraph c d -> Expected Metrics
predictPerformance [] _ = Left "No history to predict from"
predictPerformance (t:_) _ = Right (metrics t)

acquireNextConfiguration :: History a b -> AgentGraph Prompt TestResult
acquireNextConfiguration _ = 
    Copy 
    >>> (Id *** QueryMCP "github-pr-server")
    >>> CallModel "claude-3-7-sonnet"
    >>> ApplySkill "linter-skill"
    >>> RunTests

data AgentGraph a b where
    Id         :: AgentGraph a a
    Seq        :: AgentGraph a b -> AgentGraph b c -> AgentGraph a c
    Par        :: AgentGraph a b -> AgentGraph c d -> AgentGraph (a, c) (b, d)
    Copy       :: AgentGraph a (a, a)
    Drop       :: AgentGraph a ()
    ApplySkill :: String -> AgentGraph String String
    QueryMCP   :: String -> AgentGraph Prompt Context
    CallModel  :: String -> AgentGraph (Prompt, Context) Code
    RunTests   :: AgentGraph Code TestResult

instance Category AgentGraph where
    id = Id
    (.) = flip Seq

instance Arrow AgentGraph where
    arr _ = error "Pure functions omitted for diagrammatic purity"
    first f = Par f Id
    (***) = Par

evaluateGraph :: AgentGraph a b -> a -> IO b
evaluateGraph Id x = return x
evaluateGraph (Seq f g) x = do
    res <- evaluateGraph f x
    evaluateGraph g res
evaluateGraph (Par f g) (x, y) = do
    resX <- evaluateGraph f x
    resY <- evaluateGraph g y
    return (resX, resY)
evaluateGraph Copy x = return (x, x)
evaluateGraph Drop _ = return ()
evaluateGraph (ApplySkill "uppercase") x = return (map toUpper x)
evaluateGraph (ApplySkill name) x = return x
evaluateGraph (QueryMCP server) prompt = return ["Context from " ++ server ++ " for: " ++ prompt]
evaluateGraph (CallModel model) (prompt, context) = return $ "Code from " ++ model
evaluateGraph RunTests code = return Pass
