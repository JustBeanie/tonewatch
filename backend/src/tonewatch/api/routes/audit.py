"""Authenticated, paginated security audit records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from tonewatch.api.deps import authenticated
from tonewatch.storage.models import AuditEvent

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit", dependencies=[Depends(authenticated)])
async def audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    actor: str | None = None,
    event_type: str | None = None,
    resource: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    if (since is not None and since.tzinfo is None) or (until is not None and until.tzinfo is None):
        raise HTTPException(422, "include a timezone offset")
    if since is not None:
        since = since.astimezone(UTC)
    if until is not None:
        until = until.astimezone(UTC)
    if since is not None and until is not None and since > until:
        raise HTTPException(422, "since must be before or equal to until")
    query = select(AuditEvent).order_by(AuditEvent.id.desc())
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    if actor is not None:
        query = query.where(AuditEvent.actor == actor)
    if event_type is not None:
        query = query.where(AuditEvent.event_type == event_type)
    if resource is not None:
        query = query.where(AuditEvent.resource == resource)
    if since is not None:
        query = query.where(AuditEvent.created_at >= since)
    if until is not None:
        query = query.where(AuditEvent.created_at <= until)
    async with request.app.state.session_factory() as session:
        rows = list((await session.scalars(query.limit(limit + 1))).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "actor": row.actor,
                "event_type": row.event_type,
                "resource": row.resource,
                "before": row.before,
                "after": row.after,
                "details": row.details,
            }
            for row in page
        ],
        "next_cursor": str(page[-1].id) if has_more else None,
    }
