"""Authenticated, paginated security audit records."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from tonewatch.api.deps import authenticated
from tonewatch.storage.models import AuditEvent

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit", dependencies=[Depends(authenticated)])
async def audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .order_by(AuditEvent.id.desc())
                    .offset(cursor)
                    .limit(limit + 1)
                )
            ).all()
        )
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
        "next_cursor": str(cursor + limit) if has_more else None,
    }
