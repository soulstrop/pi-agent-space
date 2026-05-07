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
      * List order in ``skills`` IS significant (skills are an ordered
        pipeline, not a set). If skills become unordered in a future
        ADR, this canonicalization changes.
      * The triple is wrapped in a typed envelope so a value cannot
        masquerade as a different field.
    """
    envelope = {
        "package": package_diff,
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
