# The Rosetta Stone (Version B: The Builder's Path)

**Perspective:** Bottom-Up (Inductive)
**Direction:** Python (The Truth) $\to$ Haskell (The Verification) $\to$ Math (The Shape)

This version is for developers who want to start with the code they know and see how it scales up into more powerful abstractions.

---

## Trace 1: The Trial Outcome (ADR 0007)

**The Python Intuition:** We need to know if a trial succeeded or crashed so we can filter our data.
**Analogy:** The `Result` type in Rust or `Either` in modern Python.

### 1. The Truth (Python Context)
We start with the "Real World" problems: messy I/O, asynchronous network calls, and defensive filtering. 

```python
# The Messy Reality: Loading and filtering trials
def analyze_results(storage_path: Path):
    # 1. IO/Globbing
    paths = storage_path.glob("trial_*/final.json")
    
    # 2. Defensive Filtering (The "Intuition")
    # We want to ignore crashes (error_escalated) and only see metrics
    # from runs that actually produced a result.
    valid_results = []
    for p in paths:
        data = json.load(p.open())
        if data["outcome"] != "error_escalated":
            valid_results.append(data["metrics"])
    return valid_results
```

### 2. The Verification (Haskell)
We take that "Defensive Filtering" intuition and make it a **Type**. Instead of manual `if/else` checks, the Haskell compiler *forces* us to handle the logic. 

```haskell
-- Verification: The data structure enforces the filtering logic
data Outcome
    = Completed Metrics
    | BoundaryViolation Metrics
    | ErrorEscalated
```

### 3. The Shape (Category Theory)
We generalize this into a **Coproduct** ($\amalg$). This is the math of "mutual exclusivity." It’s the universal law that governs why our `if/else` logic works.

---

## Trace 2: Composition (The Workflow)

**The Python Intuition:** We want to chain tools together or run them in parallel.
**Analogy:** Middleware in FastAPI or Pipes in a shell.

### 1. The Truth (Python Context)
In the "Real World," parallel workflows are handled by `asyncio.gather`. It's powerful but easy to "miswire" (e.g., passing the output of `Haiku` to something that expects `Opus`'s schema).

```python
# The Messy Reality: Coordinating sub-agents
async def run_sub_agents(prompt, context):
    # Parallel execution with asyncio
    haiku_res, opus_res = await asyncio.gather(
        haiku_explore(prompt, context),
        opus_plan(prompt, context)
    )
    # Manual string merging
    return f"Explore: {haiku_res}\nPlan: {opus_res}"
```

### 2. The Verification (Haskell)
We formalize how these skills "plug in" to each other using **Arrows**. This prevents "wiring bugs" before the code even runs.

**Visualization: The Typed Wire**
```mermaid
flowchart LR
    A[Prompt] -- "String" --> B(Skill A)
    B -- "List" --> C(Skill B)
    C -- "Result" --> D[Outcome]
```

### 3. The Shape (Category Theory)
We recognize this as a **Monoidal Category**. It tells us that we can treat complex workflows exactly like simple ones. If "A then B" is a valid agent, and "C then D" is a valid agent, then "(A then B) in parallel with (C then D)" is also a valid agent.

---

## Summary: Scaling Your Intuition

| Your Intuition | The Formal Tool | The Mathematical Law |
| :--- | :--- | :--- |
| "It's one of these three things" | Sum Type / Enum | Coproduct ($\amalg$) |
| "Do A, then do B" | Composition (`>>>`) | Morphism Composition ($\circ$) |
| "Do A and B at the same time" | Parallel Tensor (`***`) | Tensor Product ($\otimes$) |
| "Filter out the noise" | Projection function | Projection ($\pi$) |
