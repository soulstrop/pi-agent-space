"""Content-addressable identity for candidate trials.

A candidate-change identity fingerprints a (package_diff, eval_suite_ref,
version_vector) triple so the optimizer can dedup proposals that are
semantically identical to ones already evaluated.
"""

from __future__ import annotations

import hashlib
import json


def candidate_identity(
    package_diff: dict,
    eval_suite_ref: dict,
    version_vector: dict,
) -> str:
    """Return a stable hex digest fingerprinting the candidate triple.

    Canonicalization rules:
      * Dict key order is irrelevant (JSON sort_keys).
      * Whitespace / pretty-printing is irrelevant.
      * ``package.skills`` is canonicalized as a sorted list. Pi treats
        ``--tools`` as order-insensitive (verified against 0.74), so
        permuted skill orderings refer to the same package.
      * The triple is wrapped in a typed envelope so a value cannot
        masquerade as a different field.
    """
    package_canonical = _canonicalize_package(package_diff)
    envelope = {
        "package": package_canonical,
        "eval_suite_ref": eval_suite_ref,
        "version_vector": version_vector,
    }
    canonical = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonicalize_package(package: dict) -> dict:
    if "skills" not in package:
        return package
    skills = package["skills"]
    if not isinstance(skills, list):
        return package
    return {**package, "skills": sorted(skills)}
