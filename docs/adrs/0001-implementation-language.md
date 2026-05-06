# Title: 0001 - Implementation Language for Evaluator and Optimizer

**Status:** Proposed

## Context
The `pi-agent-space` project requires an operational environment to evaluate and optimize the categorical models designed in our Haskell DSL. This environment must perform two distinct functions:
1. **The Evaluator:** Spin up configurations of the `pi` coding agent (which is implemented natively in TypeScript) and measure performance metrics (e.g., token consumption, quality).
2. **The Optimizer:** Run a combinatorial Bayesian Optimization loop, extracting the Pareto frontier and training a surrogate model (e.g., a Graph Kernel or Graph Neural Network) to select the next configuration.

We must decide on the primary language and runtime for this system.

## Options Considered

### 1. Python
Python is the dominant language for AI engineering, data science, and mathematical optimization.

* **Pros:**
  * **Rich ML Ecosystem:** Access to mature optimization libraries (like BoTorch, scikit-optimize, Ray Tune) and Graph Neural Network libraries (PyTorch Geometric) for building the surrogate model.
  * **Rapid Prototyping:** Extremely fast to script the evaluation loops, data collection, and plotting of the Pareto frontier.
* **Cons:**
  * **Ecosystem Mismatch:** The `pi` agent harness is written in TypeScript. A Python test bench cannot import `pi` natively; it must invoke the agent as a subprocess (CLI) or via an IPC/API layer, complicating fine-grained control and telemetry extraction.

### 2. TypeScript
TypeScript is the native language of the `pi` mono-repo (`@badlogic/pi-mono`).

* **Pros:**
  * **Native Integration:** We can directly import `pi` types, tools, commands, and events. This allows us to programmatically construct the agent harness, inject mock data, and extract internal telemetry without bridging a language barrier.
  * **Type Safety:** The strict typing aligns well with the formal categorical structures we've modeled in Haskell.
* **Cons:**
  * **Immature ML Ecosystem:** The ecosystem for Bayesian Optimization, Gaussian Processes, and Graph Kernels in JavaScript/TypeScript is practically non-existent. We would either have to implement the optimization mathematics from scratch or offload the math to a separate microservice.

## Decision
*(Pending user decision)*

## Reconsider Trigger
*(To be populated after decision)*

## Consequences
*(To be populated after decision)*