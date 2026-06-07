"""Unit tests for the persisted-telemetry secret redactor (ADR 0020 D1)."""

from __future__ import annotations

from pi_evaluator.domain.redaction import REDACTED, redact_json, redact_secrets


class TestRedactSecrets:
    def test_openai_sk_key_is_redacted(self):
        text = "auth failed with sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
        assert "sk-proj-" not in redact_secrets(text)
        assert REDACTED in redact_secrets(text)

    def test_anthropic_sk_ant_key_is_redacted(self):
        text = "ANTHROPIC_API_KEY=sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFFGGGG1234"
        out = redact_secrets(text)
        assert "sk-ant-api03" not in out
        assert REDACTED in out

    def test_google_aiza_key_is_redacted(self):
        text = "key AIzaSyA1234567890abcdefghijklmnopqrstuvw used"
        out = redact_secrets(text)
        assert "AIza" not in out
        assert REDACTED in out

    def test_bearer_token_redacted_header_preserved(self):
        text = "Authorization: Bearer eyJhbG.ciOiJI.UzI1NiN9-abc_DEF"
        out = redact_secrets(text)
        assert "eyJhbG" not in out
        assert out == f"Authorization: Bearer {REDACTED}"

    def test_x_api_key_header_value_redacted_name_preserved(self):
        text = "x-api-key: sk-proj-shortbuttagged0123456789abcd"
        out = redact_secrets(text)
        assert "x-api-key:" in out
        assert "sk-proj-shortbuttagged" not in out
        assert out.endswith(REDACTED)

    def test_x_api_key_with_equals_separator(self):
        text = "x-api-key=AIzaSyA1234567890abcdefghijklmnopqrstuvw"
        out = redact_secrets(text)
        assert "AIza" not in out
        assert "x-api-key" in out

    def test_short_hyphenated_word_is_not_redacted(self):
        # below the length floor: not a key shape
        text = "trial sk-001 finished"
        assert redact_secrets(text) == text

    def test_non_secret_text_passes_through_unchanged(self):
        text = "tokens=1234 cost=$0.02 model=claude-opus-4-8"
        assert redact_secrets(text) == text

    def test_redaction_is_idempotent(self):
        text = "leaked sk-proj-abcdefghijklmnopqrstuvwxyz0123456789 here"
        once = redact_secrets(text)
        assert redact_secrets(once) == once

    def test_multiple_secrets_in_one_string(self):
        text = (
            "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789 and "
            "AIzaSyA1234567890abcdefghijklmnopqrstuvw"
        )
        out = redact_secrets(text)
        assert "sk-proj-" not in out
        assert "AIza" not in out
        assert out.count(REDACTED) == 2


class TestRedactJson:
    def test_redacts_string_values_in_dict(self):
        obj = {"stderr": "boom sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"}
        out = redact_json(obj)
        assert "sk-proj-" not in out["stderr"]
        assert REDACTED in out["stderr"]

    def test_recurses_into_nested_lists_and_dicts(self):
        obj = {
            "payload": {
                "malformed_lines": [
                    "ok line",
                    "AIzaSyA1234567890abcdefghijklmnopqrstuvw",
                ]
            }
        }
        out = redact_json(obj)
        assert out["payload"]["malformed_lines"][0] == "ok line"
        assert "AIza" not in out["payload"]["malformed_lines"][1]

    def test_keys_are_not_redacted(self):
        # a key shaped like a secret is a field name, not telemetry
        obj = {"sk-proj-abcdefghijklmnopqrstuvwxyz0123456789": "value"}
        out = redact_json(obj)
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789" in out

    def test_scalars_pass_through(self):
        obj = {"tokens": 1234, "rate": 0.5, "ok": True, "missing": None}
        assert redact_json(obj) == obj

    def test_input_is_not_mutated(self):
        obj = {"stderr": "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"}
        redact_json(obj)
        assert obj["stderr"] == "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
