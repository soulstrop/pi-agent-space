from pi_evaluator.domain.types import RawTelemetry
from pi_evaluator.lifecycle import is_model_error


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
