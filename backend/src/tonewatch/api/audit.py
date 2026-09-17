"""Append-only security audit events and redacted configuration diffs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from tonewatch.storage.models import AuditEvent

_SECRET_WORDS = ("password", "secret", "token", "authorization", "cookie", "csrf")
_SECRET_PLURAL_WORDS = frozenset(f"{word}s" for word in _SECRET_WORDS)
_EXPLICIT_SECRET_KEYS = frozenset({"api_key", "private_key", "passphrase", "x-api-key"})


class SecretRestoreError(ValueError):
    """A masked credential could not be matched to a stored credential."""


def is_secret_key(key: object) -> bool:
    """Return whether a field name identifies a value that must be redacted."""
    normalized = str(key).casefold()
    if normalized in _EXPLICIT_SECRET_KEYS:
        return True
    segments = [segment for segment in re.split(r"[_-]+", normalized) if segment]
    return bool(segments) and segments[-1] in {*_SECRET_WORDS, *_SECRET_PLURAL_WORDS}


def mask_secrets(value: Any) -> Any:
    """Recursively replace values whose field names identify credentials."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_secret_key(key) else mask_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


def restore_secrets(stored: Any, submitted: Any) -> Any:
    """Restore real stored credentials where a masked response was submitted back."""
    if isinstance(submitted, dict):
        if not isinstance(stored, dict):
            for key, value in submitted.items():
                if is_secret_key(key) and value == "[REDACTED]":
                    raise SecretRestoreError(f"redacted placeholder has no stored value for {key}")
                restore_secrets(None, value)
            return submitted
        restored: dict[Any, Any] = {}
        for key, value in submitted.items():
            if is_secret_key(key) and value == "[REDACTED]":
                stored_value = stored.get(key)
                if stored_value in (None, ""):
                    raise SecretRestoreError(f"redacted placeholder has no stored value for {key}")
                restored[key] = stored_value
            else:
                restored[key] = restore_secrets(stored.get(key), value)
        return restored
    if isinstance(submitted, list):
        if not isinstance(stored, list):
            for item in submitted:
                restore_secrets(None, item)
            return submitted
        stored_by_id = {
            item.get("id"): item
            for item in stored
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        stored_has_ids = bool(stored_by_id)
        submitted_has_ids = any(
            isinstance(item, dict) and isinstance(item.get("id"), str) for item in submitted
        )
        positional_matching = not stored_has_ids and not submitted_has_ids
        return [
            restore_secrets(
                (
                    stored_by_id.get(item.get("id"))
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                    else stored[index]
                    if positional_matching and index < len(stored)
                    else None
                ),
                item,
            )
            for index, item in enumerate(submitted)
        ]
    return submitted


async def record_audit(
    session_factory: Any,
    *,
    actor: str,
    event_type: str,
    resource: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist one masked audit record without exposing secret values."""
    if session_factory is None:
        return
    context = session_factory()
    if not hasattr(context, "__aenter__"):
        return
    async with context as session:
        if not hasattr(session, "add"):
            return
        session.add(
            AuditEvent(
                created_at=datetime.now(UTC),
                actor=actor,
                event_type=event_type,
                resource=resource,
                before=mask_secrets(before),
                after=mask_secrets(after),
                details=mask_secrets(details),
            )
        )
        await session.commit()
