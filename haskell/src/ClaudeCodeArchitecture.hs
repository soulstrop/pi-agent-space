{-# LANGUAGE GADTs #-}
module ClaudeCodeArchitecture where

import Prelude hiding (id, (.))
import Control.Category
import Control.Arrow
import AgentSpace

-- | Models the "Coordinator Mode" and "Lead-agent-plus-subagents" pattern.
-- Forks the context to parallel sub-agents (Explore, Plan)
coordinatorSubAgents :: AgentGraph (Prompt, Context) Code
coordinatorSubAgents = 
    -- Fork context
    Copy 
    -- Run Explore Sub-agent and Plan Sub-agent in parallel (Teammate mode)
    >>> ( (Id >>> CallModel "Claude-3-Haiku-Explore") 
          *** 
          (Id >>> CallModel "Claude-3-Opus-Plan")
        )
    -- Gather and merge the isolated sub-agent outputs
    >>> MergeStrings

-- | Models the KAIROS "Always-On" autonomous daemon mode
kairosDaemon :: AgentGraph Code Code
kairosDaemon = ApplySkill "KAIROS_Background_Refactor"

-- | Models the Undercover Mode (stripping metadata)
undercoverMode :: AgentGraph Code Code
undercoverMode = ApplySkill "Strip_CoAuthoredBy_Metadata"

-- | The full Claude Code Agentic Harness Workflow
claudeCodeWorkflow :: AgentGraph (Prompt, Context) TestResult
claudeCodeWorkflow = 
    -- 1. Coordinator spawns sub-agents in parallel and merges results
    coordinatorSubAgents
    -- 2. KAIROS daemon runs in the background to refine code
    >>> kairosDaemon
    -- 3. Undercover mode strips metadata
    >>> undercoverMode
    -- 4. Finally validate the changes
    >>> RunTests

-- | The Claude Code "Dreaming" (Memory Consolidation) Loop
-- Models the auto-compacting routine that handles token limits.
-- We use ArrowLoop to feed the compacted context back into the next iteration.
dreamingLoop :: AgentGraph Code TestResult
dreamingLoop = loop DreamSkill