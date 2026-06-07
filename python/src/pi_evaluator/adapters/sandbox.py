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
) -> SandboxPort:
    """Select the isolation strategy for a *real* agent run (ADR 0009, j8x).

    Hard-fail posture: agents must not run unisolated by accident.

    * If ``bwrap`` can actually create a sandbox on this host, return a
      ``BwrapSandbox`` (with the Pi install directory bound read-only).
    * Otherwise **refuse** — raise ``RuntimeError`` — unless the operator has
      explicitly opted out via ``PI_ALLOW_UNSANDBOXED`` (or ``allow_unsandboxed
      =True``), in which case return ``NullSandbox`` after a loud warning.

    ``allow_unsandboxed`` takes precedence over the environment when not
    ``None`` (``False`` forces the refusal even if the env var is set).
    """
    if bwrap_available(bwrap_binary):
        return BwrapSandbox(
            bwrap_binary=bwrap_binary,
            extra_ro_binds=_pi_install_binds(pi_binary),
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
