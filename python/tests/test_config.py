"""Tests for the central configuration registry (ADR 0023).

Covers ``Settings`` defaults, ``from_env`` parsing (including malformed-value
rejection), ``validate`` (the ``gfm`` startup-validation contract), and the
drift guard that keeps ``Settings`` defaults in lockstep with the constructor
defaults of the components they feed (ADR 0023 Consequences).
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from datetime import timedelta

import pytest

from pi_evaluator.config import ConfigError, Settings

# A minimal env that satisfies validate()'s provider-key requirement.
_KEYED_ENV = {"ANTHROPIC_API_KEY": "sk-test"}


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_defaults_match_current_constants() -> None:
    s = Settings()
    assert s.per_trial_cost_cap_usd is None
    assert s.per_run_cost_cap_usd is None
    assert s.cost_cap_warning_fraction == 0.8
    assert s.retry_budget == 2
    assert s.retry_backoff_seconds == (30.0, 60.0)
    assert s.retry_jitter_range == (0.5, 1.5)
    assert s.max_consecutive_errors is None
    assert s.max_time_without_completed_trial is None
    assert s.bootstrap_threshold == 10


def test_settings_is_frozen() -> None:
    s = Settings()
    # setattr (not a direct assignment) keeps the static type-checker from
    # flagging the deliberately-illegal write before runtime exercises it.
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(s, "retry_budget", 5)


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


def test_from_env_empty_env_yields_defaults() -> None:
    assert Settings.from_env({}) == Settings()


def test_from_env_parses_all_fields() -> None:
    env = {
        "PI_EVAL_PER_TRIAL_COST_CAP_USD": "0.50",
        "PI_EVAL_PER_RUN_COST_CAP_USD": "20",
        "PI_EVAL_COST_CAP_WARNING_FRACTION": "0.9",
        "PI_EVAL_RETRY_BUDGET": "3",
        "PI_EVAL_RETRY_BACKOFF_SECONDS": "10,20,40",
        "PI_EVAL_RETRY_JITTER_RANGE": "0.25,1.75",
        "PI_EVAL_MAX_CONSECUTIVE_ERRORS": "5",
        "PI_EVAL_MAX_TIME_WITHOUT_COMPLETED_TRIAL": "900",
        "PI_EVAL_BOOTSTRAP_THRESHOLD": "7",
    }
    s = Settings.from_env(env)
    assert s.per_trial_cost_cap_usd == 0.50
    assert s.per_run_cost_cap_usd == 20.0
    assert s.cost_cap_warning_fraction == 0.9
    assert s.retry_budget == 3
    assert s.retry_backoff_seconds == (10.0, 20.0, 40.0)
    assert s.retry_jitter_range == (0.25, 1.75)
    assert s.max_consecutive_errors == 5
    assert s.max_time_without_completed_trial == timedelta(seconds=900)
    assert s.bootstrap_threshold == 7


def test_from_env_ignores_unprefixed_and_unknown_vars() -> None:
    env = {
        "RETRY_BUDGET": "99",  # missing PI_EVAL_ prefix -> ignored
        "PI_EVAL_NOT_A_FIELD": "x",  # unknown -> ignored
        "ANTHROPIC_API_KEY": "sk-test",  # provider key is unprefixed by design
    }
    assert Settings.from_env(env) == Settings()


def test_from_env_rejects_malformed_float() -> None:
    with pytest.raises(ConfigError, match="PI_EVAL_PER_TRIAL_COST_CAP_USD"):
        Settings.from_env({"PI_EVAL_PER_TRIAL_COST_CAP_USD": "not-a-number"})


def test_from_env_rejects_malformed_int() -> None:
    with pytest.raises(ConfigError, match="PI_EVAL_RETRY_BUDGET"):
        Settings.from_env({"PI_EVAL_RETRY_BUDGET": "2.5"})


def test_from_env_rejects_empty_backoff_list() -> None:
    with pytest.raises(ConfigError, match="PI_EVAL_RETRY_BACKOFF_SECONDS"):
        Settings.from_env({"PI_EVAL_RETRY_BACKOFF_SECONDS": " , "})


def test_from_env_rejects_malformed_jitter_range_arity() -> None:
    with pytest.raises(ConfigError, match="PI_EVAL_RETRY_JITTER_RANGE"):
        Settings.from_env({"PI_EVAL_RETRY_JITTER_RANGE": "0.5,1.0,1.5"})


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_passes_with_a_provider_key() -> None:
    Settings().validate(env=_KEYED_ENV)  # no raise


@pytest.mark.parametrize(
    "key", ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
)
def test_validate_accepts_any_selectable_provider_key(key: str) -> None:
    Settings().validate(env={key: "sk-test"})  # no raise


def test_validate_requires_a_provider_key() -> None:
    with pytest.raises(ConfigError, match="API key"):
        Settings().validate(env={})


def test_validate_google_alternate_key_does_not_satisfy_alone() -> None:
    # GOOGLE_API_KEY is an alternate that does not select a model on its own
    # (.env.example); it must not satisfy the presence check by itself.
    with pytest.raises(ConfigError, match="API key"):
        Settings().validate(env={"GOOGLE_API_KEY": "sk-test"})


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5])
def test_validate_rejects_warning_fraction_out_of_range(fraction: float) -> None:
    with pytest.raises(ConfigError, match="cost_cap_warning_fraction"):
        Settings(cost_cap_warning_fraction=fraction).validate(env=_KEYED_ENV)


def test_validate_accepts_warning_fraction_at_upper_bound() -> None:
    Settings(cost_cap_warning_fraction=1.0).validate(env=_KEYED_ENV)


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        (Settings(per_trial_cost_cap_usd=0.0), "per_trial_cost_cap_usd"),
        (Settings(per_run_cost_cap_usd=0.0), "per_run_cost_cap_usd"),
    ],
)
def test_validate_rejects_non_positive_cap(settings: Settings, field: str) -> None:
    with pytest.raises(ConfigError, match=field):
        settings.validate(env=_KEYED_ENV)


def test_validate_allows_unset_caps() -> None:
    Settings(per_trial_cost_cap_usd=None, per_run_cost_cap_usd=None).validate(
        env=_KEYED_ENV
    )


def test_validate_rejects_negative_retry_budget() -> None:
    with pytest.raises(ConfigError, match="retry_budget"):
        Settings(retry_budget=-1).validate(env=_KEYED_ENV)


def test_validate_rejects_negative_bootstrap_threshold() -> None:
    with pytest.raises(ConfigError, match="bootstrap_threshold"):
        Settings(bootstrap_threshold=-1).validate(env=_KEYED_ENV)


def test_validate_rejects_empty_backoff_schedule() -> None:
    with pytest.raises(ConfigError, match="retry_backoff_seconds"):
        Settings(retry_backoff_seconds=()).validate(env=_KEYED_ENV)


def test_validate_rejects_negative_backoff_value() -> None:
    with pytest.raises(ConfigError, match="retry_backoff_seconds"):
        Settings(retry_backoff_seconds=(30.0, -1.0)).validate(env=_KEYED_ENV)


def test_validate_rejects_inverted_jitter_range() -> None:
    with pytest.raises(ConfigError, match="retry_jitter_range"):
        Settings(retry_jitter_range=(1.5, 0.5)).validate(env=_KEYED_ENV)


def test_validate_rejects_negative_jitter_low() -> None:
    with pytest.raises(ConfigError, match="retry_jitter_range"):
        Settings(retry_jitter_range=(-0.1, 1.5)).validate(env=_KEYED_ENV)


# ---------------------------------------------------------------------------
# Drift guard: Settings defaults must equal the components' constructor defaults
# (ADR 0023 Consequences). The test layer may import both freely; src must not.
# ---------------------------------------------------------------------------


def _default(fn: Callable[..., object], name: str) -> object:
    return inspect.signature(fn).parameters[name].default


def test_defaults_match_cli_subprocess_adapter() -> None:
    from pi_evaluator.adapters.cli_subprocess_adapter import CliSubprocessAdapter

    s = Settings()
    init = CliSubprocessAdapter.__init__
    assert _default(init, "retry_budget") == s.retry_budget
    assert _default(init, "backoff_seconds") == s.retry_backoff_seconds
    assert _default(init, "retry_jitter_range") == s.retry_jitter_range


def test_defaults_match_trial_runner() -> None:
    from pi_evaluator.trial_runner import TrialRunner

    s = Settings()
    assert (
        _default(TrialRunner.__init__, "cost_cap_warning_fraction")
        == s.cost_cap_warning_fraction
    )


def test_defaults_match_optimizer_driver() -> None:
    from pi_evaluator.optimizer_driver import OptimizerDriver

    s = Settings()
    init = OptimizerDriver.__init__
    assert _default(init, "cost_cap_warning_fraction") == s.cost_cap_warning_fraction
    assert _default(init, "retry_budget") == s.retry_budget
    assert _default(init, "bootstrap_threshold") == s.bootstrap_threshold
    assert _default(init, "per_trial_cost_cap_usd") == s.per_trial_cost_cap_usd
    assert _default(init, "per_run_cost_cap_usd") == s.per_run_cost_cap_usd
    assert _default(init, "max_consecutive_errors") == s.max_consecutive_errors
    assert (
        _default(init, "max_time_without_completed_trial")
        == s.max_time_without_completed_trial
    )
