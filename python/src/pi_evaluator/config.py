"""Central configuration registry and startup validation (ADR 0023).

A single typed source of truth for the operational knobs that govern an
optimization run — cost caps, retry/backoff, circuit-breaker thresholds, and the
proposer bootstrap point. The previously scattered module constants
(``COST_CAP_WARNING_FRACTION``, ``DEFAULT_RETRY_BACKOFF_SECONDS``,
``RETRY_JITTER_RANGE``) live here as field defaults.

This module sits at the **edge** of the hexagon, beside ``logging_config``. It
reads the environment (I/O), so it must never be imported by ``domain/`` or the
adapters — that would invert the dependency arrows. The composition root reads a
``Settings`` instance and passes its fields *down* into the existing constructor
parameters of ``CliSubprocessAdapter``, ``TrialRunner``, and ``OptimizerDriver``;
the registry is a new *source* for those arguments, not a replacement for the
injection seam. ``Settings`` is distinct from ``domain.types.RunConfig``: this is
the env-aware, validated source-of-truth; ``RunConfig`` is the per-run persisted
snapshot (ADR 0013).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import timedelta

# The provider API keys the acceptance suite selects from, in precedence order
# (see .env.example). GOOGLE_API_KEY is an alternate that does not select a model
# on its own, so it deliberately does not satisfy the presence check below.
PROVIDER_KEY_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)

_ENV_PREFIX = "PI_EVAL_"


class ConfigError(Exception):
    """Configuration is missing a required value or is otherwise incoherent.

    Raised by :meth:`Settings.from_env` on a malformed environment value and by
    :meth:`Settings.validate` when a required value is absent or out of range.
    The message is operator-facing and actionable.
    """


@dataclass(frozen=True)
class Settings:
    """Typed, immutable registry of operational configuration (ADR 0023).

    Field defaults are the canonical v1 values. They are intentionally
    duplicated in the matching constructor parameters of the components these
    feed; ``test_config.py`` asserts the two stay in lockstep.
    """

    per_trial_cost_cap_usd: float | None = None
    """ADR 0005 per-trial hard cap in dollars; ``None`` means no cap."""

    per_run_cost_cap_usd: float | None = None
    """ADR 0005 per-run hard cap in dollars; ``None`` means no cap."""

    cost_cap_warning_fraction: float = 0.8
    """ADR 0005 soft-warning threshold as a fraction of the hard cap.

    A single symmetric fraction (not a warn/halt split) — relocated from a code
    constant to an env-tunable knob, but still one knob."""

    retry_budget: int = 2
    """ADR 0007 B1 adapter-layer retries on top of the initial attempt."""

    retry_backoff_seconds: tuple[float, ...] = (30.0, 60.0)
    """Backoff schedule; index ``i`` is the wait before retry ``i+1``. If shorter
    than the budget, the last entry is reused for further retries."""

    retry_jitter_range: tuple[float, float] = (0.5, 1.5)
    """Multiplicative jitter ``(low, high)`` applied to each backoff wait so
    evaluators hitting the same transient error don't retry in lockstep."""

    max_consecutive_errors: int | None = None
    """ADR 0007 circuit-breaker error threshold; ``None`` disables it."""

    max_time_without_completed_trial: timedelta | None = None
    """ADR 0007 circuit-breaker time threshold; ``None`` disables it."""

    bootstrap_threshold: int = 10
    """ADR 0006 proposer bootstrap point (load-bearing once the Phase 6
    surrogate proposer lands)."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build a ``Settings`` from ``PI_EVAL_``-prefixed environment variables.

        Absent variables fall back to the field defaults. Variables without the
        prefix and unknown ``PI_EVAL_`` names are ignored. A present-but-malformed
        value raises :class:`ConfigError` naming the offending variable.
        """
        env = os.environ if env is None else env

        return cls(
            per_trial_cost_cap_usd=_opt_float(env, "PER_TRIAL_COST_CAP_USD"),
            per_run_cost_cap_usd=_opt_float(env, "PER_RUN_COST_CAP_USD"),
            cost_cap_warning_fraction=_float(
                env, "COST_CAP_WARNING_FRACTION", cls.cost_cap_warning_fraction
            ),
            retry_budget=_int(env, "RETRY_BUDGET", cls.retry_budget),
            retry_backoff_seconds=_float_tuple(
                env, "RETRY_BACKOFF_SECONDS", cls.retry_backoff_seconds
            ),
            retry_jitter_range=_jitter_range(
                env, "RETRY_JITTER_RANGE", cls.retry_jitter_range
            ),
            max_consecutive_errors=_opt_int(env, "MAX_CONSECUTIVE_ERRORS"),
            max_time_without_completed_trial=_opt_timedelta(
                env, "MAX_TIME_WITHOUT_COMPLETED_TRIAL"
            ),
            bootstrap_threshold=_int(
                env, "BOOTSTRAP_THRESHOLD", cls.bootstrap_threshold
            ),
        )

    def validate(self, env: Mapping[str, str] | None = None) -> None:
        """Abort with :class:`ConfigError` if the configuration is unusable.

        The ``gfm`` startup-validation contract: at least one selectable provider
        API key must be present, and the operational values must be coherent
        (warning fraction in ``(0, 1]``, positive caps if set, non-negative
        budgets, a sane backoff schedule and jitter range).
        """
        env = os.environ if env is None else env

        if not any(env.get(k) for k in PROVIDER_KEY_ENV_VARS):
            raise ConfigError(
                "No provider API key found. Set one of "
                f"{', '.join(PROVIDER_KEY_ENV_VARS)} before running."
            )

        if not 0.0 < self.cost_cap_warning_fraction <= 1.0:
            raise ConfigError(
                "cost_cap_warning_fraction must be in (0, 1]; got "
                f"{self.cost_cap_warning_fraction}."
            )

        for name in ("per_trial_cost_cap_usd", "per_run_cost_cap_usd"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ConfigError(f"{name} must be positive if set; got {value}.")

        if self.retry_budget < 0:
            raise ConfigError(
                f"retry_budget must be non-negative; got {self.retry_budget}."
            )

        if self.bootstrap_threshold < 0:
            raise ConfigError(
                "bootstrap_threshold must be non-negative; got "
                f"{self.bootstrap_threshold}."
            )

        if not self.retry_backoff_seconds:
            raise ConfigError("retry_backoff_seconds must not be empty.")
        if any(s < 0 for s in self.retry_backoff_seconds):
            raise ConfigError(
                "retry_backoff_seconds values must be non-negative; got "
                f"{self.retry_backoff_seconds}."
            )

        low, high = self.retry_jitter_range
        if not 0 <= low <= high:
            raise ConfigError(
                "retry_jitter_range must be (low, high) with 0 <= low <= high; "
                f"got {self.retry_jitter_range}."
            )


# ---------------------------------------------------------------------------
# Env parsing helpers. Each raises ConfigError naming the full PI_EVAL_ variable
# when a present value cannot be parsed; absent values fall back to the default.
# ---------------------------------------------------------------------------


def _raw(env: Mapping[str, str], suffix: str) -> str | None:
    value = env.get(_ENV_PREFIX + suffix)
    return value if value not in (None, "") else None


def _float(env: Mapping[str, str], suffix: str, default: float) -> float:
    raw = _raw(env, suffix)
    return default if raw is None else _parse_float(suffix, raw)


def _opt_float(env: Mapping[str, str], suffix: str) -> float | None:
    raw = _raw(env, suffix)
    return None if raw is None else _parse_float(suffix, raw)


def _int(env: Mapping[str, str], suffix: str, default: int) -> int:
    raw = _raw(env, suffix)
    return default if raw is None else _parse_int(suffix, raw)


def _opt_int(env: Mapping[str, str], suffix: str) -> int | None:
    raw = _raw(env, suffix)
    return None if raw is None else _parse_int(suffix, raw)


def _opt_timedelta(env: Mapping[str, str], suffix: str) -> timedelta | None:
    raw = _raw(env, suffix)
    return None if raw is None else timedelta(seconds=_parse_float(suffix, raw))


def _float_tuple(
    env: Mapping[str, str], suffix: str, default: tuple[float, ...]
) -> tuple[float, ...]:
    raw = _raw(env, suffix)
    if raw is None:
        return default
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ConfigError(f"{_ENV_PREFIX + suffix} must list at least one number.")
    return tuple(_parse_float(suffix, p) for p in parts)


def _jitter_range(
    env: Mapping[str, str], suffix: str, default: tuple[float, float]
) -> tuple[float, float]:
    raw = _raw(env, suffix)
    if raw is None:
        return default
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        raise ConfigError(
            f"{_ENV_PREFIX + suffix} must be exactly two numbers 'low,high'; "
            f"got {raw!r}."
        )
    return (_parse_float(suffix, parts[0]), _parse_float(suffix, parts[1]))


def _parse_float(suffix: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{_ENV_PREFIX + suffix} must be a number; got {raw!r}."
        ) from exc


def _parse_int(suffix: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{_ENV_PREFIX + suffix} must be an integer; got {raw!r}."
        ) from exc


# Guard against silent drift if a field is added without a from_env mapping.
_PARSED_SUFFIXES = {
    "PER_TRIAL_COST_CAP_USD",
    "PER_RUN_COST_CAP_USD",
    "COST_CAP_WARNING_FRACTION",
    "RETRY_BUDGET",
    "RETRY_BACKOFF_SECONDS",
    "RETRY_JITTER_RANGE",
    "MAX_CONSECUTIVE_ERRORS",
    "MAX_TIME_WITHOUT_COMPLETED_TRIAL",
    "BOOTSTRAP_THRESHOLD",
}
assert _PARSED_SUFFIXES == {f.name.upper() for f in fields(Settings)}, (
    "Settings fields and from_env parsing have drifted; update both."
)
