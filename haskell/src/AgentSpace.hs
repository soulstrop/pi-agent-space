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

-- | Trial outcome per ADR 0007. The optimizer's surrogate sees
-- 'Completed' and 'BoundaryViolation' (the latter teaches the cost
-- cliff in feature space); 'ErrorEscalated' is preserved for
-- asynchronous human classification and does not feed the surrogate.
data Outcome
    = Completed Metrics
    | BoundaryViolation Metrics
    | ErrorEscalated
    deriving (Show, Eq)

-- | Project an outcome to its metric-bearing branch.
metricsOf :: Outcome -> Maybe Metrics
metricsOf (Completed m) = Just m
metricsOf (BoundaryViolation m) = Just m
metricsOf ErrorEscalated = Nothing

data Trial a b = Trial
    { config  :: AgentGraph a b
    , outcome :: Outcome
    }

-- | Pareto frontier over the metric-bearing projection of trial
-- outcomes. Error-escalated trials are dropped before frontier
-- computation since they carry no metric.
paretoFrontier :: [Trial a b] -> [Trial a b]
paretoFrontier trials =
    [ t | t <- trials, hasMetrics t, not (isDominated t trials) ]
  where
    hasMetrics t = case metricsOf (outcome t) of
        Just _  -> True
        Nothing -> False
    isDominated t ts = any (\other ->
        case (metricsOf (outcome other), metricsOf (outcome t)) of
            (Just mo, Just mt) ->
                tokensConsumed mo <= tokensConsumed mt &&
                qualityScore mo >= qualityScore mt &&
                mo /= mt
            _ -> False) ts

type History a b = [Trial a b]

-- | Heteroscedastic estimate per ADR 0006: the surrogate models both
-- the mean and an input-dependent variance. The variance object has
-- the same structural shape as the mean, so 'tokensConsumed' on the
-- variance carries Var[tokens], 'qualityScore' carries Var[quality].
data NoisyEstimate a = NoisyEstimate
    { mean     :: a
    , variance :: a
    } deriving (Show, Eq)

-- | Surrogate prediction. ADR 0006 commits to a heteroscedastic GP:
-- the trial map @(config, problem) -> metrics@ is non-deterministic
-- and the noise level varies with the configuration. The surrogate
-- returns mean and input-dependent variance; below the bootstrap
-- threshold the variance estimate is unreliable and acquisition
-- falls back to pure exploration.
--
-- v1 stub: returns the most recent observed metrics with zero
-- variance. The Phase 6 surrogate replaces this with a fitted
-- HetGP.
predictPerformance :: History a b -> AgentGraph c d -> Either String (NoisyEstimate Metrics)
predictPerformance [] _ = Left "No history to predict from"
predictPerformance (t:_) _ = case metricsOf (outcome t) of
    Just m  -> Right NoisyEstimate { mean = m, variance = zeroVariance }
    Nothing -> Left "Most recent trial has no metrics (error-escalated)"
  where
    zeroVariance = Metrics { tokensConsumed = 0, qualityScore = 0 }

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
    ApplyContextSkill :: String -> AgentGraph Context Context
    ExtractCode :: AgentGraph (Code, ()) Code
    QueryMCP   :: String -> AgentGraph Prompt Context
    CallModel  :: String -> AgentGraph (Prompt, Context) Code
    CallParameterizedModel :: String -> AgentGraph (ModelParams, (Prompt, Context)) Code
    RunTests   :: AgentGraph Code TestResult
    MergeStrings :: AgentGraph (String, String) String
    DreamSkill :: AgentGraph (Code, Context) (TestResult, Context)
    SubscribeStream :: AgentGraph (Prompt, Context) ()

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
evaluateGraph (ApplyContextSkill name) ctx = return (name : ctx)
evaluateGraph ExtractCode (code, _) = return code
evaluateGraph (QueryMCP server) prompt = return ["Context from " ++ server ++ " for: " ++ prompt]
evaluateGraph (CallModel model) (prompt, context) = return $ "Code from " ++ model
evaluateGraph (CallParameterizedModel model) (params, (prompt, context)) = 
    return $ "Code from " ++ model ++ " at temp " ++ show (temperature params)
evaluateGraph RunTests code = return Pass
evaluateGraph MergeStrings (s1, s2) = return (s1 ++ "\n" ++ s2)
evaluateGraph DreamSkill (code, _) = return (Pass, ["compacted memory for " ++ code])
evaluateGraph SubscribeStream _ = return ()

evaluatePara :: ParaGraph p a b -> p -> a -> IO b
evaluatePara (Para g) p a = evaluateGraph g (p, a)
