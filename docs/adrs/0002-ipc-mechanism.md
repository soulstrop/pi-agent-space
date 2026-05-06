# Title: 0002 - Inter-Process Communication (IPC) between Python Optimizer and Pi Agent

**Status:** Proposed

## Context
In ADR 0001, we established that the `pi-agent-space` Bayesian Optimization and Pareto analysis loop will be implemented in Python. However, the target system being optimized---the Pi coding agent---is implemented natively in TypeScript. We intend to treat the Pi harness as a black box, orchestrating it from the outside to measure token consumption and solution quality against graduated problems. 

We must define the Inter-Process Communication (IPC) mechanism that the Python orchestrator will use to configure, launch, and extract telemetry from the Pi agent.

## Options Considered

### 1. CLI Execution with JSON Event Streaming
The Python orchestrator spawns the Pi agent as a subprocess using standard CLI commands (e.g., `pi run`). Configuration is passed via environment variables, CLI flags, or by dynamically generating a `pi.json` configuration file before execution. The Pi agent is configured to output its telemetry and results as a JSON event stream to `stdout`, which the Python process consumes.

* **Pros:**
  * **True Black Box:** Absolutely minimal coupling. Python simply executes a shell command and reads text.
  * **Easy Setup:** No persistent servers or complex networking required.
  * **Reproducibility:** Each execution is a clean, isolated subprocess, minimizing state leakage between Bayesian Optimization trials.
* **Cons:**
  * **High Latency:** Booting the Node.js runtime and the Pi harness for every single trial incurs significant cold-start overhead, which adds up over thousands of optimization rounds.
  * **Limited Interactivity:** Harder to inject dynamic mock data or intercept mid-flight execution without complex `stdin` manipulation.

### 2. RPC Mode (Remote Procedure Call)
The Pi harness is launched in a persistent background daemon mode, exposing an RPC interface (e.g., JSON-RPC over WebSockets or HTTP). The Python orchestrator acts as a client, sending configuration payloads to initiate an evaluation run and receiving asynchronous telemetry events back.

* **Pros:**
  * **Low Latency:** The Node.js runtime and Pi harness stay warm in memory between trials.
  * **Clean API Boundary:** Formalized contract for sending commands and receiving telemetry without parsing raw `stdout` streams.
* **Cons:**
  * **State Management:** Requires careful management to ensure the daemon is cleanly reset between trials so that previous context/memory doesn't poison the next configuration run.
  * **Development Overhead:** Requires configuring and maintaining the Pi RPC server and the Python client networking logic.

### 3. TypeScript SDK Wrapper (The "OpenClaw" approach)
We write a thin TypeScript/Node.js evaluation script using the Pi SDK (similar to the OpenClaw architecture). The Python optimizer communicates with this specific script via a simple, custom IPC protocol (like ZeroMQ or named pipes).

* **Pros:**
  * **Maximum Flexibility:** The TS wrapper can utilize the full depth of the `createAgentSession()` SDK to precisely hook into events, track telemetry, and apply custom tools or compaction safeguards natively.
  * **Tailored Outputs:** The TS wrapper can calculate the exact metrics (tokens, exact match quality) and return a clean, single response to Python, offloading parsing logic.
* **Cons:**
  * **Breaks Black-Box Paradigm:** We are no longer treating Pi purely as a black-box executable, but writing custom TypeScript code tightly coupled to its internal SDK.
  * **Dual-Language Maintenance:** Requires maintaining significant operational code in both Python and TypeScript.

## Decision
We will defer locking into a single IPC mechanism at this stage. Instead, we will design the Python evaluator using **Hexagonal Architecture (Ports and Adapters)**. 

The core Bayesian Optimization loop and Pareto analysis logic will interact with the Pi agent exclusively through an abstract `AgentHarnessPort`. We will build specific adapters for the different IPC mechanisms (e.g., `CliStreamAdapter`, `RpcAdapter`, `SdkWrapperAdapter`) as needed. We will initially implement the adapter that offers the lowest barrier to entry for development (likely the CLI with JSON Event Streaming) and swap to higher-performance adapters (like RPC) later if deployment scenarios or latency requirements demand it.

## Reconsider Trigger
We will reconsider this architectural pattern if maintaining multiple adapters becomes too burdensome, or if the abstraction layer prevents us from accessing critical optimization telemetry that requires a tighter coupling to the Pi internals.

## Consequences
* **Decoupled Design:** The core optimization mathematics remain completely insulated from the underlying infrastructure and execution context of the Pi agent.
* **Delayed Commitment:** We retain the flexibility to choose the most appropriate deployment and IPC strategy later when operational requirements are clearer.
* **Increased Initial Abstraction:** Developers must adhere to strict interface boundaries (`AgentHarnessPort`) rather than making direct system calls or RPC requests within the optimization loop.
* **Adapter Maintenance:** We may need to build and maintain multiple adapters as our understanding of the performance bottlenecks evolves.