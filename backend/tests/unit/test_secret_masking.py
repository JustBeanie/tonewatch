"""Regression tests for precise secret-key matching."""

from __future__ import annotations

import pytest
import structlog
from structlog.testing import LogCapture

from tonewatch.api.audit import SecretRestoreError, is_secret_key, mask_secrets, restore_secrets
from tonewatch.logging import _redact


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("token_ttl_s", False),
        ("password", True),
        ("ui_password", True),
        ("mqtt_password", True),
        ("secret", True),
        ("live_secret", True),
        ("api_token", True),
        ("Authorization", True),
        ("Cookie", True),
        ("X-CSRF-Token", True),
        ("api_key", True),
        ("private_key", True),
        ("passphrase", True),
        ("x-api-key", True),
        ("cookies", True),
        ("passwords", True),
        ("secrets", True),
        ("tokens", True),
        ("mqtt_target_id", False),
    ],
)
def test_secret_key_matching(key: str, expected: bool) -> None:
    assert is_secret_key(key) is expected


def test_mask_secrets_preserves_non_secret_token_fields() -> None:
    payload = {"token_ttl_s": 3600, "api_token": "hidden"}

    assert mask_secrets(payload) == {"token_ttl_s": 3600, "api_token": "[REDACTED]"}


def test_log_redaction_keeps_conservative_substring_matching() -> None:
    capture = LogCapture()
    sensitive_values = {
        "cookies": "cookie-" + "value",
        "token_hash": "hash-" + "value",
        "x_csrf_token": "csrf-" + "value",
        "token_ttl_s": 3600,
    }
    redacted = "[REDACTED]"
    old_config = structlog.get_config()
    try:
        structlog.configure(
            processors=[_redact, capture],
            cache_logger_on_first_use=False,
        )
        structlog.get_logger("test").info("sensitive", **sensitive_values)
    finally:
        structlog.configure(**old_config)
    event = capture.entries[0]
    assert event["cookies"] == redacted
    assert event["token_hash"] == redacted
    assert event["x_csrf_token"] == redacted
    assert event["token_ttl_s"] == redacted


def test_restore_secrets_does_not_cross_restore_unmatched_idless_items() -> None:
    stored = [
        {"id": "first", "password": "first-secret"},
        {"id": "second", "password": "second-secret"},
    ]
    reordered_without_ids = [
        {"name": "second", "password": "[REDACTED]"},
        {"name": "first", "password": "[REDACTED]"},
    ]

    with pytest.raises(SecretRestoreError, match="no stored value"):
        restore_secrets(stored, reordered_without_ids)
