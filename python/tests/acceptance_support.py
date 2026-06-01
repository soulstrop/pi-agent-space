"""Shared scaffolding for real-Pi acceptance tests (ADR 0010).

Imported by ``test_acceptance_phase{2,3,6}``.  Centralizing provider
detection and skip-gating here keeps them identical across phases so the
runtime contract can't drift.  Per-phase concerns (slot spaces, suite/
version vectors, assertions) stay in the individual test modules.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRADUATED_PROBLEMS_DIR = REPO_ROOT / "graduated_problems"

# Order is preference — first available key wins. Each entry maps an
# API-key env var to a Pi "provider/model" string.
PROVIDER_FALLBACKS: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "google/gemini-2.5-flash"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
]

VALID_OUTCOMES = {"completed", "boundary_violation", "error_escalated"}


def require_pi_and_model() -> str:
    """Return the provider model to use, or ``pytest.skip`` the test.

    Skips when the ``pi`` binary is not on PATH or no recognised provider
    API key is in the environment — the two prerequisites every real-Pi
    acceptance test shares.
    """
    if shutil.which("pi") is None:
        pytest.skip("`pi` binary not on PATH")
    for env_var, model in PROVIDER_FALLBACKS:
        if os.environ.get(env_var):
            return model
    pytest.skip(
        "no provider API key found "
        f"(looked for: {', '.join(v for v, _ in PROVIDER_FALLBACKS)})"
    )
