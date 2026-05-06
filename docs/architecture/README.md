# Architecture

This directory contains architecture documentation for pi-agent-space.

## Modeling Complex Architectures: The Claude Code Example

The `AgentGraph` DSL constructed in Haskell is highly expressive and capable of cleanly modeling complex, real-world agentic architectures. To demonstrate this, we mapped the concepts revealed in the March 2026 Anthropic Claude Code leak to our categorical framework.

### 1. "Coordinator Mode" and "Lead-agent-plus-subagents" (Teammate Mode)
The Claude Code architecture coordinates a session and spawns isolated sub-agents for parallel work to boost efficiency. In our DSL, we represent this using the strict monoidal tensor product (`***` or `Par`) and the `Copy` routing primitive to safely duplicate context, followed by a `MergeStrings` morphism to gather the results.

```haskell
-- Forks the context to parallel sub-agents (Explore, Plan)
coordinatorSubAgents :: AgentGraph (Prompt, Context) Code
coordinatorSubAgents = 
    -- Fork context safely
    Copy 
    -- Run Explore Sub-agent and Plan Sub-agent in mathematically isolated parallel processes
    >>> ( (Id >>> CallModel "Claude-3-Haiku-Explore") 
          *** 
          (Id >>> CallModel "Claude-3-Opus-Plan")
        )
    -- Gather and merge the isolated sub-agent outputs
    >>> MergeStrings
```

### 2. "Dreaming" (Memory Consolidation)
The leak highlighted a "Dreaming" routine that auto-compacts older conversations to manage token limits. Because this involves taking a modified context and feeding it *back* into the loop, it cannot be modeled by a simple Directed Acyclic Graph (DAG). We use the Category Theory concept of a **Trace**, implemented in our DSL via `ArrowLoop`.

```haskell
-- | The Claude Code "Dreaming" (Memory Consolidation) Loop
-- We use ArrowLoop to trace the compacted context back into the next iteration.
dreamingLoop :: AgentGraph Code Code
dreamingLoop = loop (Par (ApplySkill "Process_Code_And_Dream") Id)
```

### 3. The Full Orchestration Pipeline (KAIROS, Undercover, etc.)
We model the sequential coordination of hidden features (such as the KAIROS autonomous background daemon and the Undercover metadata-stripping mode) as modular skills (`ApplySkill`) strung together safely using categorical composition (`>>>`):

```haskell
-- | The full Claude Code Agentic Harness Workflow
claudeCodeWorkflow :: AgentGraph (Prompt, Context) TestResult
claudeCodeWorkflow = 
    -- 1. Coordinator spawns sub-agents in parallel and merges results
    coordinatorSubAgents
    -- 2. KAIROS daemon runs in the background to refine code
    >>> ApplySkill "KAIROS_Background_Refactor"
    -- 3. Undercover mode strips metadata
    >>> ApplySkill "Strip_CoAuthoredBy_Metadata"
    -- 4. Finally validate the changes
    >>> RunTests
```

Because of the strict typing of the `AgentGraph` GADT, the Haskell compiler mathematically proves that the topological connections between sub-components are well-formed (e.g., the output of the KAIROS daemon matches the required input for Undercover Mode, which flows correctly into validation). This guarantees the lack of deadlocks or type-mismatches across distributed agent graphs before deployment.