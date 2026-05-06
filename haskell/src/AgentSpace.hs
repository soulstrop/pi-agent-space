{-# LANGUAGE GADTs #-}

module AgentSpace where

import Prelude hiding (id, (.))
import Control.Category
import Control.Arrow
import Control.Monad.Fix (mfix)
import Data.Char (toUpper)

type Prompt  = String
type Context = [String]
type Code    = String
data TestResult = Pass | Fail String deriving (Show, Eq)

data Metrics = Metrics 
    { tokensConsumed :: Int
    , qualityScore   :: Float
    } deriving (Show, Eq)

data ModelParams = ModelParams 
    { temperature :: Float 
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
    Choice     :: AgentGraph a b -> AgentGraph c d -> AgentGraph (Either a c) (Either b d)
    Loop       :: AgentGraph (b, d) (c, d) -> AgentGraph b c
    ApplySkill :: String -> AgentGraph String String
    QueryMCP   :: String -> AgentGraph Prompt Context
    CallModel  :: String -> AgentGraph (Prompt, Context) Code
    CallParameterizedModel :: String -> AgentGraph (ModelParams, (Prompt, Context)) Code
    RunTests   :: AgentGraph Code TestResult
    MergeStrings :: AgentGraph (String, String) String
    DreamSkill :: AgentGraph (Code, Context) (TestResult, Context)

data ParaGraph p a b = Para (AgentGraph (p, a) b)

instance Category AgentGraph where
    id = Id
    (.) = flip Seq

instance Arrow AgentGraph where
    arr _ = error "Pure functions omitted for diagrammatic purity"
    first f = Par f Id
    (***) = Par

instance ArrowChoice AgentGraph where
    left f = Choice f Id
    right f = Choice Id f
    (+++) = Choice

instance ArrowLoop AgentGraph where
    loop = Loop

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
evaluateGraph (Choice f _) (Left x) = do
    res <- evaluateGraph f x
    return (Left res)
evaluateGraph (Choice _ g) (Right y) = do
    res <- evaluateGraph g y
    return (Right res)
evaluateGraph (Loop f) b = do
    (c, _) <- mfix (\ ~(_, d) -> evaluateGraph f (b, d))
    return c
evaluateGraph (ApplySkill "uppercase") x = return (map toUpper x)
evaluateGraph (ApplySkill name) x = return x
evaluateGraph (QueryMCP server) prompt = return ["Context from " ++ server ++ " for: " ++ prompt]
evaluateGraph (CallModel model) (prompt, context) = return $ "Code from " ++ model
evaluateGraph (CallParameterizedModel model) (params, (prompt, context)) = 
    return $ "Code from " ++ model ++ " at temp " ++ show (temperature params)
evaluateGraph RunTests code = return Pass
evaluateGraph MergeStrings (s1, s2) = return (s1 ++ "\n" ++ s2)
evaluateGraph DreamSkill (code, _) = return (Pass, ["compacted memory for " ++ code])

evaluatePara :: ParaGraph p a b -> p -> a -> IO b
evaluatePara (Para g) p a = evaluateGraph g (p, a)
