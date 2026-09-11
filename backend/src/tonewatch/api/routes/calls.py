"""Call list and detail routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from tonewatch.api.deps import _dump, authenticated, base_path
from tonewatch.storage.models import AlertAttempt, Call, CallToneSet, Recording

router = APIRouter(prefix="/api", tags=["calls"])


def _call_dump(call: Call) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "started_at": call.started_at.isoformat(),
        "source_id": call.source_id,
        "status": call.status,
    }


async def _rows(request: Request, statement: Any) -> list[Any]:
    async with request.app.state.session_factory() as session:
        return list((await session.scalars(statement)).all())


@router.get("/calls", dependencies=[Depends(authenticated)])
async def list_calls(
    request: Request,
    source_id: str | None = None,
    toneset_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1),
    cursor: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    limit = min(limit, 200)
    statement = select(Call).order_by(Call.started_at, Call.id)
    if source_id:
        statement = statement.where(Call.source_id == source_id)
    if since:
        statement = statement.where(Call.started_at >= since)
    if until:
        statement = statement.where(Call.started_at <= until)
    rows = await _rows(request, statement)
    if toneset_id:
        tone_rows = await _rows(
            request, select(CallToneSet).where(CallToneSet.toneset_id == toneset_id)
        )
        ids = {row.call_id for row in tone_rows}
        rows = [row for row in rows if row.id in ids]
    page = rows[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(rows) else None
    return {
        "items": [_call_dump(row) for row in page],
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
    }


@router.get("/calls/{call_id}", dependencies=[Depends(authenticated)])
async def call_detail(request: Request, call_id: UUID) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "not found")
        tones = list(
            (await session.scalars(select(CallToneSet).where(CallToneSet.call_id == call_id))).all()
        )
        recordings = list(
            (await session.scalars(select(Recording).where(Recording.call_id == call_id))).all()
        )
        alerts = list(
            (
                await session.scalars(select(AlertAttempt).where(AlertAttempt.call_id == call_id))
            ).all()
        )
    prefix = base_path(request)
    return {
        **_call_dump(call),
        "tone_sets": [
            {
                "toneset_id": row.toneset_id,
                "detected_at": row.detected_at.isoformat(),
                "matched_segment_freqs": row.matched_segment_freqs,
            }
            for row in tones
        ],
        "recordings": [
            {
                "id": row.id,
                "format": row.format,
                "duration_s": row.duration_s,
                "size_bytes": row.size_bytes,
                "url": f"{prefix}/api/recordings/{row.id}",
            }
            for row in recordings
        ],
        "alert_attempts": [_dump(row) for row in alerts],
    }
