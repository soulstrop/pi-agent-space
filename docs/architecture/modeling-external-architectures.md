# Modeling External Architectures with the Haskell DSL

A useful test of pi-agent-space's categorical model is whether it can describe real-world agent architectures cleanly. This document walks through two case studies — one speculative, one deployed — that exercise the `AgentGraph` DSL on architectures we did not design. The cases are not ports of these systems into pi-agent-space; they are demonstrations that the categorical primitives chosen for the DSL (and therefore reflected in the Python's `Package` shape and the optimizer's slot space) are expressive enough to describe the architectures we care about optimizing.

For an orientation to the DSL itself — what `AgentSpace.hs` defines, how `Ports.hs` cuts the domain — see [`haskell.md`](haskell.md). For the Python implementation that everything ultimately serves, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

> **Forward note.** These case studies live in Haskell because that's where the design started. Once the Python implementation supports multi-role packages (the mixed-squad workflows of ADR 0005, expected in Phase 5+), they should be re-expressed as runnable Python `Package` configurations the optimizer can actually drive. Treat the present Haskell form as a stepping stone.

---

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
dreamingLoop :: AgentGraph Code TestResult
dreamingLoop = loop DreamSkill
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

## Modeling Embedded Architectures: The OpenClaw Example

OpenClaw implements a messaging gateway architecture by directly importing and instantiating Pi's `AgentSession` rather than spawning it as a subprocess. This embedded approach requires custom tool injection, dynamic system prompt construction based on context, and parallel event subscription to stream intermediate results (block chunking).

Our Haskell categorical DSL easily accommodates this embedded paradigm:

### 1. The Tool Policy Pipeline
Instead of relying on Pi's default tools, OpenClaw constructs a custom pipeline that applies strict policies, normalizes schemas to handle specific provider quirks, and enforces sandbox path constraints. We model this sequence of context-modifying operations using `ApplyContextSkill`:

```haskell
toolPipeline :: AgentGraph Context Context
toolPipeline = 
    ApplyContextSkill "Filter_Tools_By_Policy"
    >>> ApplyContextSkill "Normalize_Tool_Schemas"
    >>> ApplyContextSkill "Enforce_Sandbox_Paths"
```

### 2. Event Subscription and Streaming
OpenClaw taps into the active agent loop to subscribe to events (e.g., `message_start`, `tool_execution`) for terminal UI updates and block chunking. In Applied Category Theory, tapping a data stream without interrupting its primary flow is represented using the `Copy` morphism and a parallel tensor product (`***`), followed by `ExtractCode` to discard the tapped stream's termination type:

```haskell
agentExecutionWithStreaming :: AgentGraph (Prompt, Context) Code
agentExecutionWithStreaming = 
    Copy
    >>> ( CallModel "OpenClaw-Embedded-Session" 
          *** 
          SubscribeStream
        )
    >>> ExtractCode
```

### 3. The OpenClaw Workflow
The full initialization and execution cycle seamlessly weaves these components together. First, the authentication profile is resolved, then the custom tool pipeline is applied, and finally, the session executes under event observation:

```haskell
openClawWorkflow :: AgentGraph (Prompt, Context) TestResult
openClawWorkflow = 
    -- 1. Setup Auth and Model Resolution
    (Id *** ApplyContextSkill "Resolve_Auth_Profile")
    -- 2. Run the Tool Pipeline to prepare the injected tools
    >>> (Id *** toolPipeline)
    -- 3. Execute the embedded session with event subscription
    >>> agentExecutionWithStreaming
    -- 4. Validate the result
    >>> RunTests
```