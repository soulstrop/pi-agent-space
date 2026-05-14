# Title: 0004 - Workspace Isolation Strategy

**Status:** Accepted (Reconsider Trigger "Concurrent trials / network isolation per trial" superseded by [ADR 0009](0009-trial-isolation-boundary.md))

## Context

Each trial runs the Pi agent against a `GraduatedProblem` whose validation depends on the *post-trial state of the workspace*. Pi's tools (`read`, `write`, `edit`, `bash`) mutate files; some tools can also reach the network, fork processes, run package managers, or invoke installed CLIs. We need an isolation policy that:

1. Keeps the source `graduated_problems/{id}/` tree pristine across trials so a new trial starts from a known initial state.
2. Lets the trial mutate "its" workspace freely without leaking state to subsequent trials of the same problem.
3. Doesn't impose more operational complexity than v1 actually needs (single-developer R&D scenario, single trial at a time, trusted graduated problems and validation steps).
4. Leaves room for future ratchets — concurrent trials, less-trusted problems, multi-tenant deployment — without forcing us to redesign the rest of the pipeline.

Phase 2 introduced `materialize_workspace(source_dir)` (`python/src/pi_evaluator/adapters/workspace.py`) which copies the source tree into a fresh `tempfile.mkdtemp()` directory before invoking Pi. The Phase 2 plan explicitly named workspace isolation as ADR-pending; this ADR formalizes the v1 choice and sets reconsider triggers.

## Options Considered

### 1. tmpdir copy (current Phase 2 implementation)

`materialize_workspace` calls `tempfile.mkdtemp()` and copies the source tree contents in. Pi runs with `cwd=<tmpdir>`. Validation runs in the same tmpdir.

* **Pros:**
  * Simple — pure stdlib (`shutil.copytree`, `tempfile`).
  * Source tree always pristine; no rollback needed.
  * Each trial gets a unique path; tmpdirs are easily inspected during debugging.
  * OS-level tmpdir reaping handles cleanup eventually.
  * No new dependencies, no daemons, no privilege requirements.
* **Cons:**
  * **Filesystem isolation only inside the tmpdir.** Pi's `bash` tool can write outside it (`cd /; touch foo`) — the tmpdir confines `cwd` but not file-system reach.
  * **Network is fully open.** Pi can hit the LLM API (which it must), but also any other URL — leaking workspace contents, downloading payloads, etc.
  * **Process namespace is shared.** A Pi-spawned process that backgrounds itself outlives the trial.
  * **No CPU / memory / disk caps.** A pathological run could fill `/tmp`.

### 2. Container isolation (Docker / podman)

Run Pi inside a container per trial. Workspace mounted as a volume; network limited to the LLM endpoint; FS / CPU / memory bounded.

* **Pros:**
  * Strong filesystem, network, and process isolation.
  * Reproducibility: image pins runtime versions.
  * Resource caps prevent runaway trials.
  * Standard tool, well understood in CI contexts.
* **Cons:**
  * Significant operational complexity for v1 — image build, Pi binary inside container, API key passing, volume mounts, image lifecycle.
  * Slows trial startup by seconds (image cold-cache).
  * Requires a container runtime to be present and configured.
  * Adds a debug layer between developer and trial state.

### 3. chroot / `pivot_root` / namespace sandboxing

Use Linux user namespaces or chroot to confine Pi's filesystem view without a full container. Network and process namespace isolation optional.

* **Pros:**
  * Lighter than containers; no image build.
  * Filesystem confinement without a runtime daemon.
* **Cons:**
  * Linux-only; rules out macOS/Windows dev.
  * Requires careful setup of `/proc`, `/dev`, and the Pi binary path inside the sandbox.
  * Less off-the-shelf than tmpdir or containers.

### 4. No isolation (run Pi directly in `graduated_problems/{id}/`)

Skip materialization; run Pi against the source tree.

* **Pros:** Trivially simple; zero overhead.
* **Cons:** Violates requirement 1 — every trial corrupts the source. Rejected at the goals level.

## Decision

We will use **Option 1: tmpdir copy** for v1.

This honors v1's stated profile (single-developer R&D, single trial at a time, trusted problems and validation steps) and keeps the implementation in the standard library. Pi's tool surface is treated as trusted — graduated problems and their validation commands come from the project's own `graduated_problems/` directory, not from external untrusted input.

The known cons (filesystem reach outside the tmpdir, open network, no resource caps) are accepted because the v1 deployment scenario does not require defending against malicious or runaway agents. The trial author writes the problem, the validation, and the system prompt; if the agent escapes the workspace, that's a debugging concern, not a security incident.

## Reconsider Triggers

Promote to a stricter isolation strategy (containers or namespaces) when any of the following hold:

* **Concurrent trials.** Phase 3+ may run multiple trials in parallel against different configurations. Shared `/tmp` is fine; shared network endpoints, file locks outside the workspace, or process bookkeeping (PIDs, sockets) become real concerns. If the optimizer goes parallel, network isolation per-trial becomes a hard requirement to keep telemetry clean.
* **Untrusted graduated problems.** If problem validation steps ever come from external sources — community submissions, scraped repos, third-party benchmark suites — the threat model flips and tmpdir's lack of confinement is no longer acceptable.
* **Enterprise A/B deployment.** The deployment-scenarios memory describes a future enterprise A/B mode where many desks emit trials simultaneously. That mode demands network egress controls, resource caps, and audit trails — a containerized approach becomes the obvious fit.
* **Resource leaks observed in practice.** A pathological Pi run that fills `/tmp` or leaves orphaned background processes — i.e., direct evidence rather than speculation — would force the question.
* **Reproducibility under non-determinism (ADR 0006 territory).** If we want to fully reproduce a trial's runtime environment for forensics, image-pinning via container is the natural answer.

When triggered, the most likely target is **Option 2 (container)** since it covers all four reconsider drivers in one move. Option 3 would only make sense if container infrastructure proves too heavy and a Linux-only deployment is acceptable.

## Consequences

* **v1 keeps a low operational floor.** Anyone with `pi`, `uv`, and `mise` can run trials; no Docker daemon, no privileged operations, no sandbox setup.
* **Debugging is direct.** A failed trial leaves a real directory under `/tmp/pi-trial-workspace-*` that the developer can `cd` into and inspect.
* **The `materialize_workspace` interface is stable.** Whatever isolation strategy replaces tmpdir copy will return the same shape (a path the adapter changes into and runs Pi against). The reconsider migration is adapter-internal.
* **Cleanup is best-effort.** OS tmpdir reaping handles long-term hygiene; trials don't `rmtree` their workspace on completion because the directory is more useful to keep around for inspection. Disk fill is a reconsider trigger, not a v1 concern.
* **The workspace contains the exact path Pi was launched from.** Validation commands run with the same `cwd`, so relative paths in `ValidationStep.command` (e.g., `pytest test_search.py`) work without translation.
