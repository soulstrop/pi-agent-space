"""Tolerant construction of domain dataclasses from persisted JSON.

Reading a dataclass off disk must not crash on keys the reader does not
recognize: a file written by a newer minor schema may carry additive fields
this code has never heard of (ADR 0019 D4, the must-ignore rule). ``tolerant``
drops those unknown keys — logging each batch at info — and constructs the
dataclass from the remainder. Fields the data omits fall back to their
dataclass defaults, which is what makes a newer reader's additive fields
backward-compatible with older files (ADR 0019 D3).

This is a general read-**boundary** discipline (ADR 0019 D8): it applies
uniformly to every persisted dataclass, independent of the ``schema_version``
an individual file carries. It lives in the domain layer so both the
persistence adapter and the typed event-payload parser (ADR 0017) can share
one seam without an upward dependency.
"""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def tolerant(cls: type[T], data: dict[str, Any], *, where: str) -> T:
    """Construct ``cls`` from ``data``, dropping (and logging) unknown keys.

    ``where`` names the source for the log (e.g. ``"versions.json"``). Missing
    keys are left to the dataclass's own defaults; a genuinely missing
    *required* field still raises, since that is a malformed file rather than a
    forward-compatibility event.
    """
    field_names = {f.name for f in fields(cls)}
    unknown = data.keys() - field_names
    if unknown:
        logger.info(
            "ignoring unknown %s fields (file newer than reader)",
            where,
            extra={
                "event": "ignored_unknown_fields",
                "where": where,
                "unknown_fields": sorted(unknown),
            },
        )
    return cls(**{k: v for k, v in data.items() if k in field_names})
