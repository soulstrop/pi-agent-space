# Operators Guide

Instructions for deploying, operating, and maintaining the pi-agent-space.

## Trial isolation: enabling `BwrapSandbox` on a Linux host

[ADR 0009](../../adrs/0009-trial-isolation-boundary.md) introduces `BwrapSandbox` as the v1 isolation mechanism for trial execution. The sandbox itself is opt-in at code wiring time, but bwrap has a host-level prerequisite that operators must satisfy: **bwrap uses Linux user namespaces internally** (regardless of whether `--unshare-user` is requested), and modern Ubuntu kernels (24.04+) ship with `kernel.apparmor_restrict_unprivileged_userns=1`, which blocks bwrap from setting up its sandbox.

**The real-`pi` path now hard-fails without a working sandbox.** The acceptance suite selects its sandbox via `select_sandbox()`, which **refuses to run the agent unisolated**: if bwrap cannot create a sandbox on the host, the run raises rather than silently falling back to no isolation. To run real trials you must therefore complete one of the Family 1 enablement paths below — or, to deliberately run *without* isolation (macOS, a throwaway VM, CI without bwrap), set `PI_ALLOW_UNSANDBOXED=1`, which falls back to `NullSandbox` and logs a loud `WARNING`. Unit tests and the smoke harness are unaffected: `CliSubprocessAdapter`'s default is still `NullSandbox`.

The visible symptom is:

```
bwrap: setting up uid map: Permission denied
```

The operator chooses one of three enablement paths. **Family 1.B (targeted AppArmor profile) is the recommended default.** The other two are documented for cases where 1.B is not viable.

### Family 1.B — Targeted AppArmor profile (recommended)

A small AppArmor profile grants the `userns,` capability only to processes executing `/usr/bin/bwrap`. The rest of the host's AppArmor enforcement stays in place. The profile body is checked into this directory as [`bwrap-apparmor.profile`](bwrap-apparmor.profile).

**1. Verify your bwrap path matches the profile path.** The profile keys off the binary's absolute path.

```bash
which bwrap
```

If `bwrap` is at a path other than `/usr/bin/bwrap`, edit `bwrap-apparmor.profile` to match before installing.

**2. Install the profile.**

```bash
sudo cp docs/guides/operators/bwrap-apparmor.profile /etc/apparmor.d/bwrap
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

`apparmor_parser -r` is "replace if loaded, install if not" — idempotent and safe to re-run after edits.

**3. Verify the profile loaded.**

```bash
sudo aa-status | grep -i bwrap
```

Expected: `bwrap` listed under "profiles are in enforce mode" or "are loaded" (typically in unconfined mode for this profile).

**4. Functional smoke test.**

```bash
bwrap --ro-bind /usr /usr --ro-bind-try /lib /lib --ro-bind-try /lib64 /lib64 /usr/bin/true \
  && echo "bwrap works" || echo "bwrap still blocked"
```

Expected: `bwrap works`. (The `/lib` / `/lib64` binds aren't required to test userns setup itself, but without them the dynamic linker isn't reachable inside the sandbox and `execvp` of any dynamically-linked binary — including `/usr/bin/true` on Ubuntu — fails with a misleading "No such file or directory" error.)

**5. Confirm via the project's integration tests.**

```bash
cd python && mise run test 2>&1 | grep -E 'test_bwrap_integration|passed|skipped'
```

Expected: the two `test_bwrap_integration_*` cases run (no `skipped`) and pass.

#### Rollback

```bash
sudo apparmor_parser -R /etc/apparmor.d/bwrap   # unload
sudo rm /etc/apparmor.d/bwrap                    # remove
```

After rollback, the smoke test in step 4 returns to `bwrap: setting up uid map: Permission denied`.

#### Sharp edge

The profile attaches by absolute binary path. If a system update reinstalls bwrap to a different path (rare, but possible when switching between distro package, snap, or homebrew-style installs), the profile silently stops applying and the `Permission denied` error returns. `sudo aa-status` is the diagnostic — bwrap should appear in the output. If it doesn't, re-verify `which bwrap` and update the profile if the path changed.

### Family 1.A — Disable the AppArmor restriction system-wide

```bash
echo 'kernel.apparmor_restrict_unprivileged_userns = 0' \
  | sudo tee /etc/sysctl.d/60-allow-userns.conf
sudo sysctl --system
```

* **When to choose this:** the host is a single-user developer workstation, you have admin authority over it, and you do not want to manage AppArmor profiles. Restores pre-Ubuntu-24.04 behavior for *all* processes on the host.
* **When not to:** any host where AppArmor's hardening of unprivileged userns is part of the security posture. The sysctl flip removes that ratchet across the board, not just for bwrap.

### Family 1.C — Setuid bwrap

```bash
sudo chmod u+s /usr/bin/bwrap
```

* **When to choose this:** AppArmor cannot be reconfigured on this host (e.g., the AppArmor subsystem is disabled or under stricter management), and you accept a setuid binary on disk.
* **When not to:** default position. Distros have generally moved away from setuid bwrap in favor of 1.A / 1.B. The design is hardened against the obvious privilege-escalation paths, but it's the least-aligned with current Linux conventions and the most-flagged by audit tooling.

### Choosing between 1.B and the alternatives

If you can do 1.B, do 1.B. The targeted profile is the smallest deviation from the host's default hardening and the only path that's reversible at per-process granularity. 1.A and 1.C exist for environments where 1.B's prerequisites (writable `/etc/apparmor.d/`, working `apparmor_parser`) are not available.

On non-Linux hosts (macOS in particular), none of the above applies — `BwrapSandbox` is Linux-only. The Linux/macOS dev loop divergence is documented in ADR 0009 and is a Reconsider Trigger for a future container-based implementation.

## OS-level resource caps (`systemd-run --scope`)

[ADR 0020](../../adrs/0020-v1-security-scope-and-threat-model.md) D2 adds a hard CPU/memory/task ceiling on the agent: on the real-`pi` path, `select_sandbox()` wraps the bwrap invocation in a `ResourceCappedSandbox`, which runs it inside a transient `systemd-run --scope` cgroup with `MemoryMax=4G`, `CPUQuota=400%`, and `TasksMax=512` by default (operator-configurable via `ResourceCaps`). This bounds a runaway agent — a memory balloon, a busy-loop, a fork-bomb — that the orchestration-layer cost/wallclock caps (ADR 0005/0007) would only catch at the next check.

**Prerequisite (unprivileged operator):** the caps use a **`--user` scope**, which needs a running user systemd manager with delegated cgroup controllers — normal for a desktop login session, but often absent in minimal CI containers or bare `ssh` shells without lingering enabled. The wrap **degrades gracefully**: if `systemd-run` cannot create a scope, the agent still runs (sandboxed by bwrap) but **without** the resource caps, and a one-time `WARNING` is logged:

```
OS resource caps unenforced: systemd-run cannot create a user scope on this host; the agent runs without MemoryMax/CPUQuota/TasksMax
```

To confirm the caps can be enforced on your host:

```bash
systemd-run --user --scope --quiet --collect -p TasksMax=16 -- true && echo "caps enforceable"
```

Running as `root` (e.g., inside a container) uses a **system** scope automatically — no user manager required. The cap *dimensions* depend on which cgroup v2 controllers are delegated to your slice; `MemoryMax` and `TasksMax` are typically delegated, `CPUQuota` sometimes is not, in which case that one dimension is silently unenforced.
