"""Run-directory path convention (ADR 0013), shared across adapters.

A single source of truth for ``<base>/runs/<run_id>`` so that the persistence
adapter (which owns the run's config/event/manifest files) and the observability
adapter (which writes ``run_summary.json``, ADR 0022) co-locate their artifacts
without either re-deriving the layout — and without the observability seam
depending on ``PersistencePort``.
"""

from __future__ import annotations

from pathlib import Path


def run_dir(base: str | Path, run_id: str) -> Path:
    """Return the directory holding one run's artifacts under ``base``."""
    return Path(base) / "runs" / run_id
