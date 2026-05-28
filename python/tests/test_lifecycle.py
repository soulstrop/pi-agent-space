from pi_evaluator.domain.types import RawTelemetry, TrialEvent
from pi_evaluator.lifecycle import classify_outcome, is_model_error


def _telemetry(events: list[dict], *, exit_code: int = 0) -> RawTelemetry:
    return RawTelemetry(
        events=events,
        exit_code=exit_code,
        validation_results=[],
        stderr="",
        malformed_lines=[],
    )


def test_clean_completion_is_not_a_model_error():
    events = [
        {
            "type": "message_end",
            "message": {"role": "assistant", "stopReason": "end_turn"},
        }
    ]
    assert not is_model_error(_telemetry(events))


def test_nonzero_exit_code_is_a_model_error():
    assert is_model_error(_telemetry([], exit_code=1))


def test_assistant_message_end_with_error_stop_reason_is_a_model_error():
    events = [
        {
            "type": "message_end",
            "message": {"role": "assistant", "stopReason": "error"},
        }
    ]
    assert is_model_error(_telemetry(events))


def test_non_assistant_message_end_with_error_is_ignored():
    events = [
        {
            "type": "message_end",
            "message": {"role": "user", "stopReason": "error"},
        }
    ]
    assert not is_model_error(_telemetry(events))


def test_non_message_end_events_are_ignored():
    events = [{"type": "message_start", "message": {"stopReason": "error"}}]
    assert not is_model_error(_telemetry(events))


def test_missing_message_field_is_safe():
    events = [{"type": "message_end"}]
    assert not is_model_error(_telemetry(events))


# --- ADR 0011 classify_outcome ---


def _boundary_event(reason: str = "per_trial_cost_cap") -> TrialEvent:
    return TrialEvent(
        phase="boundary_violation",
        timestamp="2026-01-01T00:00:00+00:00",
        payload={"reason": reason},
    )


def _benign_event(phase: str = "scored_objective") -> TrialEvent:
    return TrialEvent(
        phase=phase,
        timestamp="2026-01-01T00:00:00+00:00",
        payload={},
    )


def _error_telemetry() -> RawTelemetry:
    return _telemetry([], exit_code=1)


def _clean_telemetry() -> RawTelemetry:
    return _telemetry([], exit_code=0)


def test_classify_outcome_empty_inputs_completes():
    assert classify_outcome([], []) == "completed"


def test_classify_outcome_clean_telemetry_completes():
    assert classify_outcome([_benign_event()], [_clean_telemetry()]) == "completed"


def test_classify_outcome_model_error_escalates():
    assert (
        classify_outcome([_benign_event()], [_error_telemetry()]) == "error_escalated"
    )


def test_classify_outcome_boundary_event_wins_over_clean_telemetry():
    events = [_benign_event(), _boundary_event()]
    assert classify_outcome(events, [_clean_telemetry()]) == "boundary_violation"


def test_classify_outcome_boundary_event_wins_over_model_error():
    """ADR 0011 precedence: a watchdog kill is source-of-kill, even if
    the surviving telemetry would otherwise classify as a model error."""
    events = [_benign_event(), _boundary_event()]
    assert classify_outcome(events, [_error_telemetry()]) == "boundary_violation"


def test_classify_outcome_multiple_boundary_events_still_boundary():
    events = [_boundary_event(), _boundary_event("subprocess_timeout")]
    assert classify_outcome(events, []) == "boundary_violation"


def test_classify_outcome_model_error_in_any_problem_escalates():
    events = [_benign_event()]
    telemetry = [_clean_telemetry(), _error_telemetry(), _clean_telemetry()]
    assert classify_outcome(events, telemetry) == "error_escalated"
