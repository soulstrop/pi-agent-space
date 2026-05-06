# Title: 0001 - Implementation Language for Evaluator and Optimizer

**Status:** Accepted

## Context
The `pi-agent-space` project requires an operational environment to evaluate and optimize the categorical models designed in our Haskell DSL. This environment must perform two distinct functions:
1. **The Evaluator:** Spin up configurations of the `pi` coding agent and measure performance metrics (e.g., token consumption, quality).
2. **The Optimizer:** Run a combinatorial Bayesian Optimization loop, extracting the Pareto frontier and training a surrogate model (e.g., a Graph Kernel or Graph Neural Network) to select the next configuration.

We must decide on the primary language and runtime for this system, choosing between Python (the standard for ML) and TypeScript (the native language of the `pi` agent).

## Options Considered

### 1. Python
Python is the dominant language for AI engineering, data science, and mathematical optimization.

* **Pros:**
  * **Rich ML Ecosystem:** Access to mature optimization libraries and Graph Neural Network libraries for building the surrogate model.
  * **Minimized Cognitive Load in ML:** Developers can leverage standard data science tooling without translating complex mathematical concepts into a different ecosystem.
  * **Black-Box Isolation:** Encourages treating the `pi` agent as a black box. Since Pi is designed to accept bundles (extensions, skills, prompts) and configuration via JSON, a Python orchestrator can manage these artifacts externally and interact via SDK, RPC mode, or JSON event stream mode.
* **Cons:**
  * **Ecosystem Mismatch:** The `pi` agent harness is written in TypeScript. A Python test bench cannot import internal `pi` telemetry directly; it must rely on observable external outputs or provided API boundaries.

### 2. TypeScript
TypeScript is the native language of the `pi` mono-repo (`@badlogic/pi-mono`).

* **Pros:**
  * **Native Integration:** We can directly import `pi` types, tools, commands, and events, allowing for deep introspection into the agent's interior state if needed.
  * **Unified Ecosystem:** If custom extensions are written in TypeScript, using TypeScript for the evaluator keeps all coding in one language paradigm (excluding the Haskell modeling).
* **Cons:**
  * **High Cognitive Load in ML:** The ecosystem for Bayesian Optimization and surrogate modeling in JS/TS is practically non-existent. Implementing these from scratch would introduce massive friction in development and operations.

## Decision
We will use **Python** as the primary implementation language for the evaluator and optimizer.

We will treat the `pi` agent as a black box as much as possible. Instrumentation for observability and telemetry will exist outside its boundary. We will manage configurations (packages, JSON configs) externally and interact with the agent via one of its supported interfaces (SDK, RPC, or JSON event stream). This approach minimizes cognitive load by allowing us to use Python's robust ML libraries for the optimization loop, which is the core complexity of this project.

## Reconsider Trigger
We will reconsider this decision if the black-box approach proves insufficient for gathering the metrics required for optimization, or if the overhead of IPC (Inter-Process Communication) between the Python orchestrator and the TypeScript Pi harness becomes a significant operational bottleneck.

## Consequences
* The team must develop expertise in managing Pi configurations and extracting telemetry via external interfaces (SDK/RPC/Event Streams).
* The ML and mathematical logic will benefit from standard Python libraries, accelerating the development of the Bayesian Optimization loop.
* We must formalize the method of interaction between the Python evaluator and the Pi agent in a subsequent ADR.
