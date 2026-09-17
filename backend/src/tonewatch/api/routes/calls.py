"""Call list and detail routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from tonewatch.api.deps import _dump, authenticated, base_path
from tonewatch.storage.models import (
    AlertAttempt,
    CadIncident,
    Call,
    CallCadIncident,
    CallToneSet,
    Recording,
)

router = APIRouter(prefix="/api", tags=["calls"])


def _call_dump(call: Call, *, has_cad: bool = False) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "started_at": call.started_at.isoformat(),
        "source_id": call.source_id,
        "status": call.status,
        "has_cad": has_cad,
    }


async def _rows(request: Request, statement: Any) -> list[Any]:
    async with request.app.state.session_factory() as session:
        return list((await session.scalars(statement)).all())


@router.get("/calls", dependencies=[Depends(authenticated)])
async def list_calls(
    request: Request,
    source_id: str | None = None,
    toneset_id: str | None = None,
    agency_id: str | None = None,
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
    if agency_id:
        tone_rows = await _rows(
            request, select(CallToneSet).where(CallToneSet.agency_id == agency_id)
        )
        ids = {row.call_id for row in tone_rows}
        rows = [row for row in rows if row.id in ids]
    page = rows[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(rows) else None
    linked_rows = (
        await _rows(
            request,
            select(CallCadIncident).where(CallCadIncident.call_id.in_([row.id for row in page])),
        )
        if page
        else []
    )
    linked_ids = {row.call_id for row in linked_rows}
    return {
        "items": [_call_dump(row, has_cad=row.id in linked_ids) for row in page],
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
        links = list(
            (
                await session.scalars(
                    select(CallCadIncident).where(CallCadIncident.call_id == call_id)
                )
            ).all()
        )
        incident_ids = {(row.feed_id, row.incident_id) for row in links}
        incidents = (
            list(
                (
                    await session.scalars(
                        select(CadIncident).where(
                            CadIncident.feed_id.in_([feed_id for feed_id, _ in incident_ids]),
                            CadIncident.incident_id.in_(
                                [incident_id for _, incident_id in incident_ids]
                            ),
                        )
                    )
                ).all()
            )
            if incident_ids
            else []
        )
        incident_map = {(row.feed_id, row.incident_id): row for row in incidents}
    prefix = base_path(request)
    return {
        **_call_dump(call, has_cad=bool(links)),
        "tone_sets": [
            {
                "toneset_id": row.toneset_id,
                "detected_at": row.detected_at.isoformat(),
                "matched_segment_freqs": row.matched_segment_freqs,
                "agency": {"id": row.agency_id, "name": row.agency_name, "kind": row.agency_kind}
                if row.agency_id is not None
                else None,
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
        "cad_incidents": [
            {
                "feed_id": row.feed_id,
                "incident_id": row.incident_id,
                "matched_at": row.matched_at.isoformat(),
                "delta_s": row.delta_s,
                "agency": {
                    "name": incident_map[(row.feed_id, row.incident_id)].agency_name,
                    "key": incident_map[(row.feed_id, row.incident_id)].agency_key,
                }
                if (row.feed_id, row.incident_id) in incident_map
                else None,
                "type": {
                    "raw": incident_map[(row.feed_id, row.incident_id)].type_raw,
                    "key": incident_map[(row.feed_id, row.incident_id)].type_key,
                    "code": incident_map[(row.feed_id, row.incident_id)].type_code,
                }
                if (row.feed_id, row.incident_id) in incident_map
                else None,
                "address_clean": incident_map[(row.feed_id, row.incident_id)].address_clean
                if (row.feed_id, row.incident_id) in incident_map
                else None,
                "cross_streets": incident_map[(row.feed_id, row.incident_id)].cross_streets
                if (row.feed_id, row.incident_id) in incident_map
                else [],
                "municipality": (
                    incident_map[(row.feed_id, row.incident_id)].municipality_name
                    or incident_map[(row.feed_id, row.incident_id)].municipality_raw
                )
                if (row.feed_id, row.incident_id) in incident_map
                else None,
                "received_at": incident_map[(row.feed_id, row.incident_id)].received_at.isoformat()
                if (row.feed_id, row.incident_id) in incident_map
                else None,
                "feed_name": next(
                    (
                        feed.name
                        for feed in request.app.state.config.cad_feeds
                        if feed.id == row.feed_id
                    ),
                    row.feed_id,
                ),
            }
            for row in links
        ],
    }
