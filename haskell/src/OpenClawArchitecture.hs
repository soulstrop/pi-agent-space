{-# LANGUAGE GADTs #-}
module OpenClawArchitecture where

import Prelude hiding (id, (.))
import Control.Category
import Control.Arrow
import AgentSpace

-- | Models the OpenClaw Tool Pipeline
-- Takes an initial Context, applies policy filtering, schema normalization, and sandbox constraints.
toolPipeline :: AgentGraph Context Context
toolPipeline = 
    -- 1. Apply Policy Filtering (allowlist/denylist per channel)
    ApplyContextSkill "Filter_Tools_By_Policy"
    -- 2. Schema Normalization for provider quirks
    >>> ApplyContextSkill "Normalize_Tool_Schemas"
    -- 3. Apply Sandbox constraints
    >>> ApplyContextSkill "Enforce_Sandbox_Paths"

-- | Models the Event Subscription and Streaming Chunker
-- In OpenClaw, the agent loop is monitored via a subscription that handles block chunking.
-- We model this as a parallel process: the main agent execution, and an event subscriber tap.
agentExecutionWithStreaming :: AgentGraph (Prompt, Context) Code
agentExecutionWithStreaming = 
    -- We copy the input so the subscriber can monitor the session parameters
    Copy
    >>> ( CallModel "OpenClaw-Embedded-Session" 
          *** 
          SubscribeStream
        )
    -- Discard the empty output from the Drop, keep the Code
    >>> ExtractCode

-- | The full OpenClaw Embedded Agent Integration Flow
openClawWorkflow :: AgentGraph (Prompt, Context) TestResult
openClawWorkflow = 
    -- 1. Setup Auth and Model Resolution (modifies Context)
    (Id *** ApplyContextSkill "Resolve_Auth_Profile")
    -- 2. Run the Tool Pipeline to prepare the injected tools
    >>> (Id *** toolPipeline)
    -- 3. Execute the embedded session with event subscription
    >>> agentExecutionWithStreaming
    -- 4. Validate the result
    >>> RunTests