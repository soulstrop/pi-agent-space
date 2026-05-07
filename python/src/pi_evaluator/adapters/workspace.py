"""Workspace materialization helper for the harness adapter.

A trial mutates the workspace it runs in (Pi writes files, runs commands,
etc.). To keep the source ``graduated_problems/{id}/`` tree pristine
across trials, we copy it into a temp directory before invoking Pi and
let the trial mutate the copy.

v1 isolation strategy: tmpdir copy. Workspace isolation is a
placeholder pending its own ADR — see implementation-plan.md
"What's deferred."
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def materialize_workspace(source_dir: str | Path) -> Path:
    """Copy ``source_dir`` into a fresh temporary directory.

    Returns the path to the new directory. The source is left
    untouched. Caller is responsible for cleanup (or trusting OS
    tmpdir reaping).
    """
    src = Path(source_dir)
    if not src.is_dir():
        raise ValueError(f"workspace source is not a directory: {src}")
    dest = Path(tempfile.mkdtemp(prefix="pi-trial-workspace-"))
    # copytree requires the dest not to exist; mkdtemp created an empty
    # dir, so copy contents into it rather than replacing.
    for entry in src.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
    return dest
