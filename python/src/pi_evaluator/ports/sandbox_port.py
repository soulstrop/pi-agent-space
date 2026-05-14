"""SandboxPort: isolation boundary for agent invocation.

The adapter materializes a workspace and then asks a ``SandboxPort``
to transform the planned ``(cmd, workspace, env)`` into the actual
invocation that ``subprocess.run`` will execute. This keeps isolation
strategy as a pluggable concern (ADR 0009): the default ``NullSandbox``
preserves Phase 1–3 behavior, while ``BwrapSandbox`` constrains the
agent's filesystem and namespace view on Linux.

The port deliberately stops at "command-line transformation." A
container-backed sandbox can satisfy the same shape (``docker run -v
…``) without touching the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SandboxedInvocation:
    """The actual command, cwd, and env to pass to ``subprocess.run``.

    Sandboxes that bind-mount the workspace at the same host path
    (``bwrap --bind X X``) return ``workspace`` unchanged. Sandboxes
    that remap (``docker run -v X:/workspace``) still return a path
    valid on the host for ``subprocess.run``'s ``cwd=``; the remapping
    is the sandbox's concern.

    ``env=None`` means inherit from the parent process. A sandbox that
    scrubs the environment returns an explicit dict.
    """

    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None


@runtime_checkable
class SandboxPort(Protocol):
    """Transform an invocation for isolated execution.

    ``cmd`` is the command the adapter wants to run (e.g.,
    ``["pi", "--print", …]``). ``workspace`` is the materialized
    trial workspace; the sandbox makes it the working directory of the
    sandboxed process. ``env`` overrides the inherited environment;
    ``None`` means inherit (subject to the sandbox's own filtering).
    """

    def wrap(
        self,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SandboxedInvocation: ...
