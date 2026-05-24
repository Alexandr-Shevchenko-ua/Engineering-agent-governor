"""Tests for secret redaction."""

from governor.redaction import redact


def test_redacts_api_key_pattern():
    text = "key=sk-abcdefghijklmnopqrstuvwxyz1234567890"
    out = redact(text)
    assert "sk-" not in out or "[REDACTED" in out


def test_redacts_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
    out = redact(text)
    assert "[REDACTED" in out


def test_redacts_password_kv():
    text = "password=supersecret123"
    out = redact(text)
    assert "supersecret123" not in out


def test_preserves_normal_text():
    text = "Changed files: src/main.py"
    assert redact(text) == text
