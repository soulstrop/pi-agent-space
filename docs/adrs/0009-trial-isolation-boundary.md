# Title: 0009 - Trial Isolation Boundary

**Status:** Accepted

*Accepted 2026-06-07. Supersedes the spike that targeted Phase 3.5.1; the
mechanism (bwrap behind `SandboxPort`) is implemented. Wiring it onto the real
execution path — and the trust-boundary / isolation-ladder framing added below —
is tracked under `pi-agent-space-j8x`.*

## Context

ADR 0004 chose `tmpdir copy` for v1 workspace isolation, explicitly accepting that "filesystem isolation [is] only inside the tmpdir … network is fully open … process namespace is shared … no CPU / memory / disk caps." Those acceptances were correct given the v1 profile but were always provisional — ADR 0004's *Reconsider Triggers* enumerate the conditions that would force the question.

External code review (beads `pi-agent-space-j8x`) re-raised the gap precisely:

> Agents are not isolated; they run as the same user and on the same host as the evaluator, with full access to the filesystem beyond the temporary workspace copy.

This ADR reframes the question — from "is isolation worth the operational cost?" to "what is the *threat model*, what mechanism family addresses it, and what does the chosen mechanism demand of the deployment host?" — and chooses a v1 isolation strategy that ratchets ADR 0004's tmpdir baseline up one level without taking on container infrastructure.

### Threat model

Three distinct concerns were being conflated under "isolation." Naming them separately is what makes the decision tractable.

**1. Measurement integrity (load-bearing for the project goal).** The project's stated purpose is honest capability profiling across `(package, problem)` cells. An agent that can read prior trials' workspaces, the evaluator's bookkeeping, the eval suite's expected outputs, or cached state from previous runs will produce numbers that are correlated with *what the host happens to contain* rather than the package's actual capability. As N grows in Phase 4, this contamination compounds — and is invisible from the trial outputs alone.

**2. Safety / credential exposure.** The evaluator's environment carries `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `~/.ssh`, `~/.config/gh`, dotfiles, and whatever else the developer has lying around. Pi has a `bash` tool and a model that can be prompted (or prompt-injected via problem text) into `env | curl`, `cat ~/.aws/credentials`, etc. The per-trial probability of harm is low; cumulative probability across the high-N runs Phase 4+ requires is not.

**3. Resource bounds.** Cost cap enforcement (ADR 0005) is wallclock + token accounting at the optimizer layer. It does not bound CPU, memory, disk, file-descriptor count, or *detached processes* spawned by the agent. A backgrounded process can outlive the trial and continue consuming resources unaccounted-for in the trial's telemetry.

The first concern is the one that pushes this from "hygiene" to "load-bearing." Even if we trusted the LLM completely, measurement integrity demands isolation.

### What the sandbox is — and isn't — trusting

The trust boundary is around the agent's **runtime behavior**, not the harness source. We control Pi's code, but Pi's purpose is to drive an LLM that *generates and executes arbitrary shell and code* against the workspace. The live adversaries are therefore (a) an LLM that misbehaves — a hallucinated `rm -rf $HOME`, a `curl … | sh` — and (b) **prompt-injection through eval content**: a crafted problem statement or fixture file that steers the agent into destruction or credential exfiltration. This is *semi-trusted execution*.

It is explicitly **not** the threat model of "untrusted code actively trying to escape the sandbox via a kernel exploit." In the individual-user R&D deployment scenario (v1's target), the operator and the agent sit on the same side of the trust line — the operator chose to run this on their own machine. That distinction is what sizes the mechanism: *escape-resistance against a hostile guest* is the property that hardware-virtualization (microVM) and userspace-kernel (gVisor) isolation buy, and it is **not** the property v1 needs. Namespace-level confinement of the agent's I/O is.

Two residual risks survive *any* mechanism choice short of a fully air-gapped guest, and are worth naming so they aren't mistakenly attributed to the isolation tier:

* **Network egress.** Pi must reach the model API, so the network cannot be cut. An agent can exfiltrate over an open socket regardless of whether it runs under bwrap, a container, or a microVM. Closing this needs egress *filtering* (allowlist the model endpoint), not a heavier sandbox.
* **Resource exhaustion.** CPU / memory / fork-bomb bounds come from cgroup limits, which attach orthogonally (`systemd-run --scope -p MemoryMax=…`, or a container's `--memory`/`--pids-limit`) at *any* tier.

Because neither residual is retired by moving to a VM, the marginal cost of a microVM does not buy down the risks that are actually live in v1. That is the core reason the decision lands on the lightweight end of the spectrum rather than at the operator's usual default of a Firecracker/QEMU microVM (which is the right default precisely when the guest *code* is unvetted — a condition that does not hold here).

### Mechanism families

Isolation mechanisms cluster into three architectural families that address the threat model by different means:

* **Namespace-based.** Use Linux kernel namespaces (mount, pid, ipc, uts, cgroup, optionally user) to give the agent a restricted view of the host. The agent runs as the evaluator's uid but cannot see what isn't bind-mounted, what isn't in its pid namespace, etc. *bwrap*, *unshare*, *firejail* are the standard tools; rootless containers are the same family at heavier weight.
* **UID-based.** Use traditional Unix permissions to deny access. Run the agent as a distinct user account whose privileges don't cross over the evaluator's files. Permissions are the *only* fence — there is no kernel-level restriction of what the agent can `stat`/`open`/`connect`, just the ordinary mode-bit and ownership checks.
* **Defense-in-depth.** Stack namespace-based isolation inside a UID-based wrapper. The threat model is closed by *either* mechanism failing alone; both have to fail to expose anything.

Each family makes different demands on the deployment host. The choice is genuinely a *deployment-scenario* question, not purely a code question, which is why this ADR separates the mechanism decision from the deployment-requirement decision.

## Options Considered

### Option 1: Status quo (tmpdir copy only, ADR 0004 v1)

* **Pros:** Zero new dependencies; works on macOS and Linux symmetrically.
* **Cons:** Addresses none of the three threats. As Phase 4 expands trial counts, all three compound.

### Option 2: Namespace-based via bwrap (bubblewrap)

The adapter prepends a `bwrap` invocation in front of `pi …`. Recipe (see `python/src/pi_evaluator/adapters/sandbox.py`):

* Read-only bind of `/usr` and via `--ro-bind-try` `/etc /lib /lib64 /lib32 /bin /sbin /opt` — the agent sees a standard system view but cannot mutate it.
* `--proc /proc`, `--dev /dev`, `--tmpfs /tmp` — minimal kernel-interface mounts.
* `--dir /tmp/home` plus `HOME=/tmp/home` in the env — agent's `$HOME` resolves to a tmpfs; **the real home directory is never bound**, so `~/.ssh`, `~/.aws`, `~/.config/gh` are simply not reachable.
* `--bind <workspace> <workspace>` and `--chdir <workspace>` — workspace is read-write at the *same path* it has on the host, so validation steps running outside the sandbox observe the same tree.
* `--unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup` — process, SysV IPC, hostname, and cgroup namespaces are unshared.
* `--unshare-user` is **not** in the default recipe (see "Bwrap deployment requirements" below).
* Network is **not** unshared — Pi must reach the model API.
* `--die-with-parent` — sandboxed processes terminate when the adapter exits, eliminating orphan-process resource leaks.
* Environment is filtered to an allowlist (`PATH`, `LANG`, `LC_ALL`, `TERM`, `TZ`, the four well-known model API keys, anything matching `PI_*`). Everything else — `AWS_*`, `GITHUB_TOKEN`, secrets the developer may have set — never enters the sandboxed process.

* **Pros:** Addresses all three threats. ~10 ms startup overhead (vs. seconds for containers). No daemon; no image lifecycle. The implementation is ~140 lines including the port abstraction. Compatible with the individual-user deployment scenario.
* **Cons:** Linux-only. Bwrap itself requires user-namespace setup *even when* `--unshare-user` is not requested — a kernel-level prerequisite (see "Bwrap deployment requirements") which not every Linux host grants by default. Process listings still show the agent as the evaluator's uid, which is fine for isolation but means traditional Unix tools (`top -u`, `ps -u`) cannot single out the agent.

### Option 3: UID-based via dedicated user account (`pi_trial:pi_trials`)

A dedicated unprivileged user account `pi_trial` runs the agent. The evaluator (the developer's user) invokes Pi through `sudo -u pi_trial --preserve-env=PATH,GEMINI_API_KEY,…` after chowning the materialized workspace to `pi_trial:pi_trials`. Traditional Unix permissions become the isolation fence:

* `~mikeco/.ssh` is mode 0700 owned by `mikeco`; `pi_trial` cannot read it.
* Prior trial workspaces, if left as `pi_trial:pi_trials` mode 0700, are invisible to subsequent trials (each gets its own tmpdir).
* `TMPDIR` is overridden to a `pi_trial`-owned directory mode 0700, so `/tmp` cross-talk is eliminated.
* `HOME` is set to a `pi_trial`-owned home directory (or `/tmp/<workspace>` to avoid persistent state).
* Environment scrubbing is free via `--preserve-env`'s allowlist behavior.
* Validation steps run as the evaluator's user against workspace contents owned by `pi_trial`; group-rwx with the evaluator joining `pi_trials` is the cleanest fit.

* **Pros:**
  * **No kernel-namespace dependency, no AppArmor entanglement.** The mechanism is decades-old Unix permission checking.
  * Smaller kernel attack surface — uid-check code is older and better-audited than namespace-setup code.
  * Process-listing transparency — `ps -u pi_trial` shows exactly what the agent is doing; useful for debugging and for operator situational awareness.
  * Composes naturally with cgroup-v2 for resource limits (`systemd-run --user --uid=pi_trial -p MemoryMax=…`) without needing userns.
  * Cross-mechanism portability: the model translates to any Unix; bwrap is Linux-only.
* **Cons:**
  * **No process-namespace isolation.** The agent can `ps -ef` and see everything else running on the host — a measurement-integrity concern if other trials are concurrent (kernel mount option `hidepid=2` on `/proc` mitigates partially).
  * **No filesystem-tree confinement.** Anything world-readable (`/etc/passwd`, system config, world-readable user files) is visible. Bwrap hides everything not explicitly bound; this option hides only what permissions deny.
  * **No process-tree death guarantee.** Detached `pi_trial`-owned processes survive the trial unless the adapter explicitly enumerates and kills them by uid.
  * Higher per-host operational footprint: user/group creation, sudoers rules (`mikeco ALL=(pi_trial) NOPASSWD: <pi binary>` plus a narrow chown rule for the workspace ownership transition), workspace permission management.
  * Sudoers is itself a security surface — getting the rule too broad creates new exposure.

### Option 4: Defense-in-depth (bwrap inside `sudo -u pi_trial`)

Stack Options 2 and 3. The agent runs as `pi_trial` *and* inside a bwrap sandbox.

* **Pros:** No single misconfiguration breaks the threat model. Process listings clearly identify trial processes (Option 3 benefit). Filesystem-tree confinement is strong (Option 2 benefit). The pi_trial account's distinct AppArmor context may also sidestep the bwrap userns restriction depending on how the host's AppArmor profile is keyed — needs verification per host.
* **Cons:** Sum of both setup costs. The marginal threat coverage over Option 2 alone is modest for the individual-user deployment scenario; the value shows up at higher trust-sensitivity scenarios.

### Option 5: Container-based (Docker / Podman per trial)

The same `SandboxPort` shape is satisfied by `docker run -v workspace:workspace ... cmd`.

* **Pros:** Strongest of the lightweight options. Cross-platform (Linux, macOS via Docker Desktop, Windows). Image pinning gives reproducibility (ADR 0006 territory). Rootless Podman avoids the daemon.
* **Cons:** 1–2 s cold-start per trial (significant at Phase 4 N). Daemon dependency for Docker; image build/lifecycle to manage. Heavier ops floor — the individual-user deployment scenario takes a real cost hit. Rootless Podman has its own userns dependency, so it inherits Option 2's "Bwrap deployment requirements" question in a different guise.

### Option 6: macOS `sandbox-exec` + bwrap on Linux behind a unified port

* **Pros:** Symmetric dev loop across platforms.
* **Cons:** `sandbox-exec` is deprecated by Apple (still works, no replacement). Profile language is fiddly and per-host. The semantics aren't quite the same — would need careful test coverage on both. Higher complexity for marginal portability gain in v1.

### Option 7: Syscall-interception (gVisor / `runsc`)

A userspace kernel (gVisor's `runsc`) intercepts the guest's syscalls, so the agent never touches the host kernel directly — escape-resistance approaching a VM's without a full guest kernel.

* **Pros:** Strong escape-resistance against a hostile guest while keeping container-style ergonomics (OCI image, cgroup limits). The natural rung *if the guest becomes genuinely untrusted but a shared host kernel is still acceptable*.
* **Cons:** Escape-resistance is the property v1 does not need (see "What the sandbox is — and isn't — trusting"). Syscall interception imposes a performance tax heaviest on I/O-bound workloads — exactly what a coding agent is — and some syscalls are unimplemented. Linux-only. Out of scope for v1.

### Option 8: microVM (Firecracker / QEMU / Kata)

* **Pros:** Strongest isolation available — a separate guest kernel behind hardware virtualization. The rung for *untrusted, multi-tenant* execution.
* **Cons:** Overkill for the v1 trust model — it buys escape-resistance v1 does not need, and does **not** retire the two live residual risks (open egress, resource caps), which attach orthogonally at any tier. Highest startup cost and ops floor (guest kernel + rootfs images, virtio-fs / network plumbing); needs nested virt where the host is itself virtualized. Out of scope for v1.

## Bwrap deployment requirements

Option 2 (and Option 4 to the extent it includes bwrap) requires the host kernel to permit `bwrap`'s user-namespace setup. **Bwrap uses user namespaces internally regardless of whether `--unshare-user` is requested** — this is how it implements `--bind` and similar without root privilege. On hosts where unprivileged user namespaces are restricted, bwrap fails with `bwrap: setting up uid map: Permission denied` before any sandboxing takes effect.

The most common restriction is Ubuntu 24.04+'s default `kernel.apparmor_restrict_unprivileged_userns=1`, which uses AppArmor to deny unprivileged userns to processes lacking an explicit grant. The operator picks one of three enablement paths:

### Family 1.A — Disable the AppArmor restriction system-wide

```
echo 'kernel.apparmor_restrict_unprivileged_userns = 0' \
  | sudo tee /etc/sysctl.d/60-allow-userns.conf
sudo sysctl --system
```

* **Pros:** One line; restores pre-24.04 behavior; works for any tool that wants userns.
* **Cons:** Removes the hardening ratchet for *all* processes on the host. Acceptable on a developer workstation under the individual-user deployment scenario; unacceptable on a managed enterprise host.

### Family 1.B — Install an AppArmor profile for bwrap (recommended)

A targeted profile grants the `userns,` capability only to processes executing `/usr/bin/bwrap`. The rest of the host's AppArmor enforcement stays in place. See the "Operator instructions" appendix below for the profile body and the load command.

* **Pros:** Surgical; aligned with how Ubuntu's hardening team expects the restriction to be relaxed; reversible per-profile.
* **Cons:** One-time setup per host; AppArmor profile syntax has its own gotchas (especially on multi-host deployments via configuration management).

### Family 1.C — Setuid bwrap

```
sudo chmod u+s /usr/bin/bwrap
```

* **Pros:** Bwrap was originally designed to run setuid; the design is hardened against the obvious privilege-escalation paths.
* **Cons:** Adds a setuid binary to the host's audit surface. Distros have generally moved away from this in favor of Family 1.A or 1.B, so it's the least-aligned with current Linux conventions.

## Decision

**Mechanism: Option 2 (namespace-based via bwrap), behind a new `SandboxPort` abstraction.**

The port shape — `wrap(cmd, workspace, env) -> SandboxedInvocation` — is satisfied equally well by Option 3 (`sudo -u pi_trial …`), Option 4 (the combination), Option 5 (`docker run -v …`), or Option 6 (`sandbox-exec …`). When future deployment scenarios force the question, replacing `BwrapSandbox` with one of these implementations is **adapter-internal**; the `AgentHarnessPort` contract, the optimizer driver, and the trial runner are untouched.

Bwrap is chosen over the UID-based and container alternatives for v1 because:

1. It addresses **all three threats** at once (Option 3 leaves process-namespace and filesystem-tree gaps; the container option pays for stronger isolation than v1 needs at multi-second-per-trial cost).
2. The implementation is **~140 lines** including the port abstraction; the operational footprint is "install bwrap and pick a Family 1 enablement option."
3. It composes with Option 3 later if defense-in-depth becomes necessary, without throwing the bwrap code away.

**Default for `CliSubprocessAdapter` remains `NullSandbox`** (the identity sandbox, preserving Phase 1–3 behavior). Callers opt into `BwrapSandbox` explicitly. This:

* Keeps existing tests untouched (no behavior change at the default).
* Keeps the dev loop working on macOS and on Linux hosts that haven't completed Family 1 setup (the explicit opt-in fails loudly with a real bwrap error, not a silent regression).
* Makes the isolation choice a deliberate decision at the wiring point, not an invisible default.

**Deployment requirement: each host running BwrapSandbox must complete one of Family 1.A / 1.B / 1.C.** The project's documentation recommends Family 1.B (targeted AppArmor profile) as the default. Family 1.A is acceptable for individual-user workstations. Family 1.C is acceptable but not preferred.

### Scope

* **Pi invocation is sandboxed.** The adapter routes the `pi …` command through the sandbox port.
* **Validation steps are not sandboxed in v1.** Per ADR 0004, graduated-problem validation commands are trusted code from the project's own repo. They run after the trial; they read workspace contents the agent may have written. The risk surface (validation tooling executing agent-authored content — e.g., `pytest` running a test file the agent created) is real but secondary, and isolating validation introduces its own complications (shell semantics across `--bind` views, validation steps that need network or non-workspace paths). Tracked as a follow-up.
* **Network is preserved.** Pi requires it. A future tightening (egress-only to the model API endpoint) is possible but not v1.
* **User namespace unsharing is not in the default recipe.** Compatibility with hardened Linux kernels takes priority; the threats this ADR addresses do not require uid-mapping protection.

### The isolation ladder

The mechanism is sized to the trust model and ratchets up *only* as that trust model degrades. Every rung is an adapter-internal swap behind `SandboxPort` — the `AgentHarnessPort` contract, optimizer, and trial runner are untouched at every step.

| Rung | Mechanism | Promote to this rung when… |
|---|---|---|
| **0 · NullSandbox** | tmpdir copy only | (default today; preserves Phase 1–3 behavior — no real isolation) |
| **1 · bwrap** *(v1 choice)* | namespaces + bind mounts + env allowlist | real trials run on a single operator's host; the goal is I/O containment + blast-radius reduction and the guest is *semi-trusted* |
| **1+ · bwrap + cgroup caps** | rung 1 wrapped in `systemd-run --scope` | runaway resource use must be bounded at the OS, not just by the cost cap (ADR 0005) |
| **2 · container** (rootless Podman) | namespaces + cgroups + image rootfs | image-pinned reproducibility or first-class resource caps are required, or cross-platform parity is wanted |
| **3 · gVisor** | userspace kernel (syscall interception) | the guest becomes *genuinely untrusted* but a shared host kernel is still acceptable |
| **4 · microVM** | hardware virt + separate guest kernel | *untrusted, multi-tenant* execution where host-kernel isolation is required |

Egress filtering and audited resource caps are **cross-cutting** concerns that attach at whichever rung is in force; they are not themselves rungs. The operator's usual "microVM by default" posture corresponds to rung 4 and is the correct default when the guest *code* is unvetted — a condition v1 does not meet, which is why v1 sits at rung 1.

## Reconsider Triggers

Move from `BwrapSandbox` to a different family (or stack them per Option 4) when any of these hold:

* **A managed deployment host refuses Family 1 enablement.** If an enterprise environment will not permit the AppArmor relaxation, the setuid bwrap binary, or the sysctl flip, Option 3 (UID-based via `pi_trial`) becomes the natural fit. The mechanism has no kernel-feature dependency at all.
* **Cross-platform symmetry becomes mandatory.** If the macOS dev loop needs to behave the same as production trial runs (currently macOS falls back to `NullSandbox`), containers via Docker Desktop / Podman (Option 5) are the obvious fix.
* **Enterprise A/B deployment scenario activates.** The deployment-scenarios memory describes a future mode where many desks emit trials concurrently. That mode wants network egress controls, audited resource caps, and image-pinned reproducibility — natural fits for Options 4 (defense-in-depth) or 5 (containers).
* **Image-pinned reproducibility becomes a requirement (ADR 0006 territory).** Container images pin the runtime environment in a way bwrap does not.
* **Validation-step taint becomes a concern.** If validation tooling running over agent-authored workspace contents proves to be a real exposure (not speculative), sandboxing validation forces a re-think of the workspace topology — a container with separate mount layers handles this more naturally than bwrap.
* **Operator audit-trail demand.** If "what processes did the trial spawn, and as what uid" becomes an audit requirement, Option 3 or 4 provides it natively in process listings; bwrap alone does not.

## Consequences

* **`AgentHarnessPort` contract is unchanged.** Optimizer, trial runner, and persistence are untouched.
* **`CliSubprocessAdapter` constructor gains one optional parameter** (`sandbox: SandboxPort | None`). Default `None` resolves to `NullSandbox`, preserving Phase 1–3 behavior.
* **The materialized workspace path is stable across the sandbox boundary.** `BwrapSandbox` binds the host workspace at the same path inside the sandbox (`--bind X X`), so absolute paths in the workspace remain valid and validation steps running outside the sandbox observe the same tree the agent wrote to.
* **The agent cannot see the evaluator's `$HOME`.** This is the most consequential single property — it kills the credential-exposure threat for any secret the evaluator carries outside the explicit allowlist.
* **The agent cannot see other trials' workspaces.** Measurement integrity threat is closed at the filesystem level. (Network-side contamination — e.g., a model provider caching responses between trials — is out of scope of this ADR.)
* **Each deployment host must complete a Family 1 enablement step.** The project documents Family 1.B as default; the operator-instructions appendix below carries the profile and load commands.
* **Tests gracefully skip integration cases** when bwrap cannot create a sandbox on the host (functional `bwrap_available()` probe). Argv-shape unit tests cover the sandbox contract without requiring bwrap to actually execute.
* **Re-running Phase 3.5 acceptance with `BwrapSandbox`** is the natural validation step before Phase 4. Out of scope for this ADR's commit; tracked as the next step in the implementation plan.

## Related

* Supersedes ADR 0004's *Reconsider Triggers* item "Concurrent trials / network isolation per trial."
* Closes beads `pi-agent-space-j8x` once `BwrapSandbox` is wired into the acceptance-test path.
* `docs/design-notes.md` carries the recipe-detail rationale (HOME tmpfs, no-unshare-user choice, env allowlist composition).
