# Title: 0003 - Trial Persistence Strategy

**Status:** Proposed

## Context
Per ADR 0002, the Python optimizer interacts with the Pi harness via an `AgentHarnessPort`. Each evaluation produces a *trial*, modeled as an ordered event stream: configuration → evaluation → objective scoring → subjective scoring → final score. The Bayesian Optimization loop accumulates these trials over long time horizons; each trial is the unit of feedback that feeds the surrogate model and the Pareto frontier.

We need a persistence strategy that supports:
1. Append-only writes during a streaming trial.
2. Direct human inspection during development (debugging the optimizer is much easier when trials are greppable).
3. Programmatic retrieval for the optimizer at the start of each round.
4. Durability across many evaluation rounds and across changes to Pi/package versions.
5. Tolerance for partially-scored trials (a trial whose subjective score has not yet arrived is still valid input to the next round).

The user has stated a preference for "simple and human-readable to begin with; migrate when things get more complicated."

## Options Considered

### 1. Per-trial directory with structured files
A directory tree of the form:
```
trials/
  {trial_id}/
    config.json     # package definition + eval-suite reference
    versions.json   # Pi version + package element versions + eval-suite version
    events.jsonl    # append-only event log for the trial
    final.json      # written when the trial closes; contains aggregated metrics
```

* **Pros:**
  * Human-readable, greppable, git-trackable.
  * Each trial is a standalone artifact — easy to inspect, copy, archive, or drop.
  * Atomic-append semantics on `events.jsonl` are trivial.
  * No daemon, no schema-migration tooling required at v0.
* **Cons:**
  * Filesystem-bound: inode pressure and slow scans at very high trial volume.
  * No built-in indexing for cross-trial queries; relies on grep/jq/find.

### 2. Single SQLite database
A single-file SQL store with tables for trials, events, scores, and version vectors.

* **Pros:**
  * Indexed cross-trial queries.
  * Transactions and consistent snapshots.
  * Single-file portability.
* **Cons:**
  * Less direct human inspection than flat files.
  * Requires upfront schema design and migration discipline.
  * Streaming-write coordination during a long-running trial is awkward.

### 3. Single append-only JSONL for all trials
One global `trials.jsonl`, one event per line, trial association via a `trial_id` field.

* **Pros:**
  * Single file to grep; minimal upfront design.
* **Cons:**
  * Locking issues under any concurrency.
  * Harder to isolate a single trial's events for inspection, cleanup, or replay.
  * No natural place for per-trial summary artifacts.

## Decision
We will use **Option 1: per-trial directory with structured files**, with the layout shown above.

This honors the stated preference for simple human-readable storage, lets v0 development proceed without upfront database investment, and keeps trials self-contained so that ad-hoc inspection, archival, and deletion are all trivial.

## Reconsider Trigger
We will reconsider this decision when any of the following hold:
* **Volume:** trial count per project exceeds roughly 10K, at which point inode pressure, scan latency, and Pareto-recomputation cost become real concerns.
* **Query complexity:** routine cross-trial queries cannot be expressed as simple grep/jq one-liners (e.g., "give me the Pareto frontier across all trials with `model = X` and `prompt_variant = Y`").
* **Concurrent writers:** multiple trial sources stream events simultaneously — most likely when the *enterprise A/B deployment scenario* lands and many desks emit trials in parallel.
* **Transactional updates:** a use case appears that requires atomic updates spanning multiple trials (e.g., bulk re-scoring after a new objective metric is added).
* **Random access at UI latency:** a UI needs sub-second by-trial-id retrieval over large histories.

When triggered, the most likely migration target is SQLite (Option 2), with the per-trial files retained as the human-readable canonical form and the database serving as an index.

## Consequences
* **Inspection-first development:** trials are self-contained directories the developer can `cat`, `jq`, or `git` without tooling.
* **Standard unix tools suffice for v1:** `find`, `grep`, `jq` cover the expected query shapes.
* **Migration cost is bounded:** moving to SQLite later is a one-time directory walk + insert; the file layout is stable enough to support both forms simultaneously.
* **Optimizer startup must scan the directory** to rebuild history — acceptable at v1 scale, an early bottleneck candidate at v2.
* **Concurrent writes are not formally supported.** A single optimizer instance writing one trial at a time is the v1 contract. Concurrency support is part of the reconsider trigger above.
