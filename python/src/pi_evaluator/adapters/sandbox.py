"""SandboxPort implementations.

* ``NullSandbox`` is the identity — used as the default to preserve
  pre-ADR-0009 behavior across the suite.
* ``BwrapSandbox`` wraps the invocation with ``bwrap`` (bubblewrap),
  giving a read-only system view, a tmpfs ``$HOME``, and unshared
  user/pid/ipc/uts/cgroup namespaces. Network is preserved (Pi
  must reach the model endpoint). Linux-only.

See ADR 0009 for the threat model and recipe rationale.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from ..ports.sandbox_port import SandboxedInvocation, SandboxPort

logger = logging.getLogger(__name__)


class NullSandbox(SandboxPort):
    """Identity sandbox: returns the invocation unchanged.

    Default for ``CliSubprocessAdapter`` so existing call sites and
    tests keep the pre-ADR-0009 behavior — no isolation, agent runs
    as the evaluator user with full filesystem reach.
    """

    def wrap(
        self,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SandboxedInvocation:
        return SandboxedInvocation(cmd=list(cmd), cwd=workspace, env=env)


DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "TZ",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
    }
)
"""Names forwarded verbatim into the sandbox.

``HOME`` is deliberately absent: ``BwrapSandbox`` mounts a tmpfs and
sets ``HOME`` to it, so the real home directory (with ``~/.ssh``,
``~/.aws``, ``~/.config/gh``) never appears inside the sandbox.

Model API keys are forwarded by name. Add provider-specific names to
the allowlist via the constructor rather than putting them in the
default — keeps the defaults explicit and auditable.
"""

DEFAULT_ENV_PREFIX_ALLOWLIST: tuple[str, ...] = ("PI_",)
"""Prefix-match allowlist. ``PI_*`` lets Pi-specific configuration
flow through without enumerating every variant."""

DEFAULT_RO_BIND_TRY: tuple[str, ...] = (
    "/usr",
    "/etc",
    "/lib",
    "/lib64",
    "/lib32",
    "/bin",
    "/sbin",
    "/opt",
)
"""Host paths read-only-bound into the sandbox via ``--ro-bind-try``.

``--ro-bind-try`` is the non-failing variant: paths that don't exist
on the host (e.g., ``/lib64`` on a 32-bit system) are silently
skipped. Without this, distro variation would break the recipe."""


class BwrapSandbox(SandboxPort):
    """Linux-only sandbox using bubblewrap (``bwrap``).

    Recipe (per ADR 0009):

    * Read-only bind of standard system paths (``/usr``, ``/etc``,
      ``/lib*``, ``/bin``, ``/sbin``, ``/opt``).
    * ``/proc`` mounted; ``/dev`` minimal.
    * Tmpfs at ``/tmp`` (and ``/home`` if the binary needs one); the
      real ``$HOME`` is not exposed.
    * The trial workspace is bind-mounted read-write at the **same
      path** as on the host, so absolute paths in the workspace stay
      valid and validation steps running outside the sandbox observe
      the same tree.
    * ``--unshare-user --unshare-pid --unshare-ipc --unshare-uts
      --unshare-cgroup`` isolates the agent from the host's user,
      process, IPC, host-name, and cgroup namespaces. **Network is
      not unshared** — Pi must reach the model API.
    * ``--die-with-parent`` ensures sandboxed processes terminate
      when the adapter goes away (no orphan agents outliving the
      trial).
    * Environment is scrubbed via the allowlist and forwarded
      through ``subprocess.run``'s ``env=`` parameter; ``HOME`` is
      set to a tmpfs path inside the sandbox.

    To support agents whose binary lives outside the default system
    paths (e.g., ``~/.local/share/mise/installs/pi/...``), pass the
    install directory in ``extra_ro_binds``.
    """

    DEFAULT_SANDBOX_HOME = "/tmp/home"

    def __init__(
        self,
        bwrap_binary: str = "bwrap",
        env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST,
        env_prefix_allowlist: tuple[str, ...] = DEFAULT_ENV_PREFIX_ALLOWLIST,
        extra_ro_binds: tuple[Path, ...] = (),
        sandbox_home: str = DEFAULT_SANDBOX_HOME,
    ) -> None:
        self._bwrap = bwrap_binary
        self._env_allowlist = env_allowlist
        self._env_prefix_allowlist = env_prefix_allowlist
        self._extra_ro_binds = tuple(Path(p).resolve() for p in extra_ro_binds)
        self._sandbox_home = sandbox_home

    def wrap(
        self,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SandboxedInvocation:
        workspace = Path(workspace).resolve()
        source_env = env if env is not None else dict(os.environ)
        filtered_env = self._filter_env(source_env)
        filtered_env["HOME"] = self._sandbox_home

        bwrap_args: list[str] = [self._bwrap]
        for path in DEFAULT_RO_BIND_TRY:
            bwrap_args.extend(["--ro-bind-try", path, path])
        for extra in self._extra_ro_binds:
            bwrap_args.extend(["--ro-bind", str(extra), str(extra)])
        bwrap_args.extend(
            [
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--dir", self._sandbox_home,
                "--bind", str(workspace), str(workspace),
                "--chdir", str(workspace),
                "--unshare-user",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--unshare-cgroup",
                "--die-with-parent",
                "--new-session",
                "--",
            ]
        )
        bwrap_args.extend(cmd)

        return SandboxedInvocation(
            cmd=bwrap_args,
            cwd=workspace,
            env=filtered_env,
        )

    def _filter_env(self, env: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in env.items():
            if key in self._env_allowlist:
                out[key] = value
                continue
            if any(key.startswith(prefix) for prefix in self._env_prefix_allowlist):
                out[key] = value
        return out


def bwrap_available(bwrap_binary: str = "bwrap") -> bool:
    """Return True if ``bwrap`` is on PATH **and** can actually create
    a sandbox on this host.

    A binary-only check is not enough: some Linux kernels (Ubuntu
    24.04+ by default) ship with ``kernel.apparmor_restrict_
    unprivileged_userns=1``, which blocks bwrap's user-namespace
    setup even when only filesystem isolation is requested. On those
    hosts ``bwrap`` exists but cannot run, so integration tests must
    skip rather than fail.
    """
    import subprocess  # local import keeps the module import side-effect free

    if shutil.which(bwrap_binary) is None:
        return False
    try:
        # The probe mirrors the real recipe's library bindings. On
        # merged-/usr systems (Ubuntu, Fedora, Arch), ``/lib64`` is a
        # symlink to ``/usr/lib64`` and the dynamic linker resolves
        # through it — without ``/lib64`` bound, ``execvp`` of a
        # dynamically-linked binary fails with ENOENT for the linker,
        # not the binary, making the failure look like a missing file.
        proc = subprocess.run(
            [
                bwrap_binary,
                "--ro-bind", "/usr", "/usr",
                "--ro-bind-try", "/lib", "/lib",
                "--ro-bind-try", "/lib64", "/lib64",
                "/usr/bin/true",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@dataclass(frozen=True)
class ResourceCaps:
    """OS-level resource caps for one sandboxed agent run (ADR 0020 D2).

    Each field maps to a systemd resource-control property enforced by the
    transient ``--scope`` cgroup that wraps the bwrap invocation. ``None``
    omits that property (no cap on that dimension). The defaults are
    conservative bounds for a single synthetic-suite trial on a developer
    workstation: enough headroom for a coding agent and its tools, low enough
    that a runaway (memory balloon, busy-loop, fork-bomb) is contained between
    the orchestration layer's cost/wallclock cap checks (ADR 0005/0007).
    """

    memory_max: str | None = "4G"  # MemoryMax — hard memory ceiling
    cpu_quota: str | None = "400%"  # CPUQuota — ~4 cores
    tasks_max: int | None = 512  # TasksMax — fork-bomb / fd-exhaustion guard

    def to_properties(self) -> list[str]:
        """Render the caps as ``-p KEY=VALUE`` pairs for ``systemd-run``."""
        props: list[str] = []
        if self.memory_max is not None:
            props.extend(["-p", f"MemoryMax={self.memory_max}"])
        if self.cpu_quota is not None:
            props.extend(["-p", f"CPUQuota={self.cpu_quota}"])
        if self.tasks_max is not None:
            props.extend(["-p", f"TasksMax={self.tasks_max}"])
        return props


def _resolve_scope_mode(scope_mode: str) -> str:
    """Resolve ``"auto"`` to ``"system"`` when root, else ``"user"``.

    An unprivileged operator must use a ``--user`` scope (the user systemd
    manager with delegated cgroup controllers); root (e.g. inside a container)
    has no user manager but can drive the system manager directly.
    """
    if scope_mode == "auto":
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        return "system" if is_root else "user"
    return scope_mode


def systemd_run_available(
    systemd_run_binary: str = "systemd-run", *, scope_mode: str = "user"
) -> bool:
    """Return True if ``systemd-run`` can create a transient ``--scope`` here.

    A binary-only check is insufficient (mirroring ``bwrap_available``): an
    unprivileged ``--user`` scope needs a running user systemd manager with
    cgroup delegation, which is absent in many CI and container environments.
    The probe creates a throwaway scope around ``true`` and checks it exits 0;
    if it can't, the caller degrades to running without caps.
    """
    import subprocess  # local import keeps the module import side-effect free

    if shutil.which(systemd_run_binary) is None:
        return False
    true_bin = shutil.which("true") or "/bin/true"
    probe = [systemd_run_binary]
    if scope_mode == "user":
        probe.append("--user")
    probe.extend(
        ["--scope", "--quiet", "--collect", "-p", "TasksMax=16", "--", true_bin]
    )
    try:
        proc = subprocess.run(
            probe, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


class ResourceCappedSandbox(SandboxPort):
    """Decorator that wraps another sandbox's command in a ``systemd-run
    --scope`` transient cgroup, enforcing OS-level CPU/memory/task caps
    (ADR 0020 D2 — realises rung 1+ of the ADR 0009 isolation ladder).

    The orchestration-layer cost (ADR 0005) and wallclock (ADR 0007) caps
    bound the *common* runaway but cannot stop CPU/memory/fd exhaustion or a
    fork-bomb *between* cap checks. A transient scope makes the kernel enforce
    hard bounds on the whole bwrap process tree. ``--unshare-cgroup`` inside
    bwrap only hides the cgroup *path* from the agent; the scope's limits still
    apply, and the agent cannot move itself out of the scope.

    **Degrades gracefully.** Whether ``systemd-run`` can create a scope is
    probed *once* at construction (the probe spins up a real transient scope,
    so it must not run per-``wrap``). When it can't, ``wrap`` returns the inner
    invocation unchanged and a one-time warning records that the caps are
    unenforced — never silently assumed.
    """

    def __init__(
        self,
        inner: SandboxPort,
        caps: ResourceCaps | None = None,
        systemd_run_binary: str = "systemd-run",
        scope_mode: str = "auto",
    ) -> None:
        self._inner = inner
        self._caps = caps if caps is not None else ResourceCaps()
        self._systemd_run = systemd_run_binary
        self._scope_mode = _resolve_scope_mode(scope_mode)
        self._enforced = systemd_run_available(
            systemd_run_binary, scope_mode=self._scope_mode
        )
        if not self._enforced:
            logger.warning(
                "OS resource caps unenforced: systemd-run cannot create a "
                "%s scope on this host; the agent runs without "
                "MemoryMax/CPUQuota/TasksMax",
                self._scope_mode,
                extra={
                    "event": "resource_caps_unenforced",
                    "scope_mode": self._scope_mode,
                    "systemd_run_binary": systemd_run_binary,
                },
            )

    def wrap(
        self,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SandboxedInvocation:
        invocation = self._inner.wrap(cmd, workspace=workspace, env=env)
        if not self._enforced:
            return invocation
        return replace(invocation, cmd=self._scope_prefix() + invocation.cmd)

    def _scope_prefix(self) -> list[str]:
        """Build the ``systemd-run --scope … --`` argv prefix.

        ``--quiet`` suppresses the "Running scope as unit" notice; ``--collect``
        garbage-collects the unit even if the command fails. With ``--scope``
        systemd-run execs the command in the foreground inside the scope,
        inheriting cwd and env — so the adapter's exit-code and ``env=``
        handling stay valid.
        """
        args = [self._systemd_run]
        if self._scope_mode == "user":
            args.append("--user")
        args.extend(["--scope", "--quiet", "--collect"])
        args.extend(self._caps.to_properties())
        args.append("--")
        return args


def _pi_install_binds(pi_binary: str) -> tuple[Path, ...]:
    """Resolve auxiliary read-only binds for the agent binary.

    Pi is often installed outside the default system paths (e.g.
    ``~/.local/share/mise/installs/pi/<ver>/...``). The dynamic linker
    resolves ``/usr`` and ``/lib*`` (already bound by the recipe), but the
    binary itself — and any siblings in its install directory — must be made
    visible. We bind the **real** install directory (following symlinks, since
    ``pi`` is frequently a shim) so the executable and its co-located resources
    are reachable inside the sandbox. Returns empty when the binary can't be
    located on PATH (e.g. an absolute path checked elsewhere, or a test stub).
    """
    resolved = shutil.which(pi_binary)
    if resolved is None:
        return ()
    install_dir = Path(resolved).resolve().parent
    return (install_dir,)


def select_sandbox(
    *,
    pi_binary: str = "pi",
    allow_unsandboxed: bool | None = None,
    bwrap_binary: str = "bwrap",
    caps: ResourceCaps | None = None,
) -> SandboxPort:
    """Select the isolation strategy for a *real* agent run (ADR 0009, j8x).

    Hard-fail posture: agents must not run unisolated by accident.

    * If ``bwrap`` can actually create a sandbox on this host, return a
      ``BwrapSandbox`` (with the Pi install directory bound read-only),
      wrapped in a ``ResourceCappedSandbox`` so the OS enforces CPU/memory/task
      caps via ``systemd-run --scope`` (ADR 0020 D2). The cap wrap degrades
      gracefully where ``systemd-run`` is absent. ``caps`` overrides the
      conservative defaults.
    * Otherwise **refuse** — raise ``RuntimeError`` — unless the operator has
      explicitly opted out via ``PI_ALLOW_UNSANDBOXED`` (or ``allow_unsandboxed
      =True``), in which case return ``NullSandbox`` after a loud warning.
      The opt-out path is deliberately unwrapped: it is an explicit "no
      isolation" escape hatch, and resource caps are tied to the bwrap path.

    ``allow_unsandboxed`` takes precedence over the environment when not
    ``None`` (``False`` forces the refusal even if the env var is set).
    """
    if bwrap_available(bwrap_binary):
        return ResourceCappedSandbox(
            BwrapSandbox(
                bwrap_binary=bwrap_binary,
                extra_ro_binds=_pi_install_binds(pi_binary),
            ),
            caps=caps,
        )

    if allow_unsandboxed is None:
        allow_unsandboxed = bool(os.environ.get("PI_ALLOW_UNSANDBOXED"))

    if allow_unsandboxed:
        logger.warning(
            "bwrap cannot sandbox on this host; running the agent UNISOLATED "
            "because PI_ALLOW_UNSANDBOXED is set",
            extra={
                "event": "sandbox_unavailable_override",
                "bwrap_binary": bwrap_binary,
            },
        )
        return NullSandbox()

    raise RuntimeError(
        "refusing to run the agent unisolated: bwrap cannot create a sandbox "
        "on this host (see ADR 0009 'Bwrap deployment requirements' for the "
        "Family 1.A/1.B/1.C enablement options). Set PI_ALLOW_UNSANDBOXED=1 to "
        "override and run without isolation."
    )
