"""Secret redaction for persisted telemetry (ADR 0020 D1).

``events.jsonl`` persists raw agent telemetry — stderr, malformed stdout
lines, raw event payloads — any of which can contain a provider API key the
agent printed. Secrets on disk outlive the run and leak the moment a run
directory is shared (a bug report, a teammate, a backup), so the persistence
write path scrubs known secret *shapes* before a line is written (ADR 0020 D1,
threat-model.md A2+A5).

This is **defence-in-depth**, not a license to log secrets: call-site
discipline (ADR 0015 MD6-A) remains the first line. The redactor only knows the
shapes of the four model providers in the ADR 0009 env allowlist — OpenAI /
Anthropic ``sk-…`` keys, Google ``AIza…`` keys — plus the two header forms
(``Authorization: Bearer …`` and ``x-api-key: …``) those keys travel in. Other
host credentials (``AWS_*``, ``GITHUB_TOKEN``) are scrubbed at the env-allowlist
boundary and never reach the agent, so they are out of this seam's scope.

It lives in the domain layer (a pure transform, no I/O, like ``tolerant_read``)
so the persistence adapter can share it without an upward dependency, and so a
future log field-allowlist (ADR 0015 MD6-B) can reuse the same shapes.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"  # noqa: S105 — placeholder, not a credential

# Each pattern matches a secret shape; the replacement keeps any non-secret
# prefix (a header name, the literal ``Bearer``) and substitutes the value.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI / Anthropic: ``sk-…``, ``sk-ant-…``, ``sk-proj-…``. The whole token
    # (>=16 token chars after ``sk-``) is the secret. Short hyphenated words
    # ("sk-001") fall below the length floor and are left alone.
    (re.compile(r"\bsk-[A-Za-z0-9._-]{16,}"), REDACTED),
    # Google API keys: ``AIza`` + 35 chars. Floor at 20 to tolerate variants.
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"), REDACTED),
    # ``Authorization: Bearer <token>`` (and bare ``Bearer <token>``). Keep the
    # ``Bearer`` literal so the redacted line still reads as an auth header.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 " + REDACTED),
    # ``x-api-key: <token>`` / ``x-api-key=<token>``. Keep the header name.
    (re.compile(r"(?i)\b(x-api-key)(\s*[:=]\s*)[A-Za-z0-9._-]+"), r"\1\2" + REDACTED),
)


def redact_secrets(text: str) -> str:
    """Scrub known provider-key shapes from a single string.

    Idempotent: re-redacting already-redacted text is a no-op (the placeholder
    matches none of the patterns).
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_json(obj: Any) -> Any:
    """Recursively redact every string in a JSON-serializable structure.

    Walks dicts (values only — keys are field names, not telemetry), lists, and
    strings; scalars (``int``/``float``/``bool``/``None``) pass through
    untouched. Returns a new structure; the input is not mutated.
    """
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {key: redact_json(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [redact_json(item) for item in obj]
    return obj
