"""Shared constructors for common test fixtures (pi-agent-space-c0w).

Centralizes how ``EvalSuiteRef`` / ``VersionVector`` are built so individual
tests declare only the fields that matter to them and the constructor shape
lives in one place — if a domain dataclass gains a field, only this module
changes. Defaults are an incidental baseline; pass overrides for any value a
test actually cares about.
"""

from __future__ import annotations

from pi_evaluator.domain.types import EvalSuiteRef, VersionVector


def make_eval_suite_ref(
    suite_id: str = "coding_v1",
    suite_version: str = "0.1.0",
) -> EvalSuiteRef:
    return EvalSuiteRef(suite_id=suite_id, suite_version=suite_version)


def make_version_vector(
    pi_version: str = "0.74.0",
    package_versions: dict[str, str] | None = None,
    eval_suite_version: str = "0.1.0",
) -> VersionVector:
    return VersionVector(
        pi_version=pi_version,
        package_versions={} if package_versions is None else package_versions,
        eval_suite_version=eval_suite_version,
    )
