"""Append-only security audit events and redacted configuration diffs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tonewatch.storage.models import AuditEvent

_SECRET_WORDS = ("password", "secret", "token", "authorization", "cookie", "csrf")


def mask_secrets(value: Any) -> Any:
    """Recursively replace values whose field names identify credentials."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(word in str(key).casefold() for word in _SECRET_WORDS)
            else mask_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


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
