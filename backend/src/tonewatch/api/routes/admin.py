"""Authenticated administrative health and alert-delivery endpoints."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from tonewatch import __version__
from tonewatch.admin.health import StorageScanner, event_bus_health, storage_forecast
from tonewatch.api.audit import record_audit
from tonewatch.api.deps import authenticated, write_auth
from tonewatch.config.models import MeshtasticTarget, MqttTarget
from tonewatch.storage.models import Call, Recording
from tonewatch.storage.repository import list_alert_attempts

router = APIRouter(prefix="/api/admin", tags=["admin"])
_STARTED = time.monotonic()


class AlertAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    call_id: UUID
    target_id: str
    phase: str
    attempt_no: int
    ok: bool
    status_code: int | None
    error: str | None
    created_at: datetime
    retry: bool


class AlertAttemptsResponse(BaseModel):
    items: list[AlertAttemptResponse]
    next_cursor: str | None


class SourceHealthResponse(BaseModel):
    id: str
    name: str
    type: str
    realtime_factor: float | None
    dropped_frames: int | None
    late_frames: int | None
    restarts: int | None
    last_restart_at: datetime | None
    last_error: str | None
    feed_health_history: list[dict[str, object]]
    level: dict[str, object] | None
    squelch_open: bool | None


class HealthResponse(BaseModel):
    generated_at: datetime
    sources: list[SourceHealthResponse]
    service: dict[str, object]
    storage: dict[str, object]
    outputs: list[dict[str, object]]
    cad_feeds: list[dict[str, object]]
    build: dict[str, object]


def _cursor(value: str | None) -> tuple[datetime, int] | None:
    if not value:
        return None
    try:
        stamp, raw_id = value.rsplit("|", 1)
        return datetime.fromisoformat(stamp), int(raw_id)
    except ValueError as exc:
        raise HTTPException(422, "invalid cursor") from exc


@router.get(
    "/alert-attempts", response_model=AlertAttemptsResponse, dependencies=[Depends(authenticated)]
)
async def alert_attempts(
    request: Request,
    call_id: UUID | None = None,
    target_id: str | None = None,
    phase: str | None = None,
    ok: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        rows = await list_alert_attempts(
            session,
            call_id=call_id,
            target_id=target_id,
            phase=phase,
            ok=ok,
            since=since,
            until=until,
            cursor=_cursor(cursor),
            limit=limit,
        )
    more = len(rows) > limit
    page = rows[:limit]
    next_value = f"{page[-1].created_at.isoformat()}|{page[-1].id}" if more and page else None
    return {
        "items": [
            row.model_dump()
            if hasattr(row, "model_dump")
            else {
                "id": row.id,
                "call_id": row.call_id,
                "target_id": row.target_id,
                "phase": row.phase,
                "attempt_no": row.attempt_no,
                "ok": row.ok,
                "status_code": row.status_code,
                "error": row.error,
                "created_at": row.created_at,
                "retry": row.retry,
            }
            for row in page
        ],
        "next_cursor": next_value,
    }


@router.post("/alert-attempts/{attempt_id}/retry", dependencies=[Depends(write_auth)])
async def retry_alert_attempt(request: Request, attempt_id: int) -> dict[str, object]:
    dispatcher = getattr(request.app.state.supervisor, "alerts", None)
    if dispatcher is None:
        raise HTTPException(404, "attempt not found")
    status, result = await dispatcher.retry_attempt(attempt_id)
    if status != 200:
        raise HTTPException(status, result["error"])
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="alert_attempt_retried",
        resource=str(attempt_id),
        details={
            "attempt_id": attempt_id,
            "target_id": result.get("target_id"),
            "ok": result["ok"],
        },
    )
    return result


@router.get("/health", response_model=HealthResponse, dependencies=[Depends(authenticated)])
async def health(request: Request) -> dict[str, object]:
    config = request.app.state.config
    supervisor = request.app.state.supervisor
    source_items: list[dict[str, object]] = []
    health_map = getattr(supervisor, "health", {}) if supervisor is not None else {}
    for source in config.sources:
        metric = health_map.get(source.id)
        status = (
            supervisor.source_status(source.id)
            if supervisor is not None and hasattr(supervisor, "source_status")
            else (None, None)
        )
        source_items.append(
            {
                "id": source.id,
                "name": source.name,
                "type": source.type,
                "realtime_factor": metric.factor.value if metric else None,
                "dropped_frames": metric.dropped_frames if metric else None,
                "late_frames": metric.late_frames if metric else None,
                "restarts": metric.restarts if metric else None,
                "last_restart_at": metric.last_restart_at if metric else None,
                "last_error": metric.last_error if metric else None,
                "feed_health_history": list(metric.feed_health_history) if metric else [],
                "level": metric.level if metric else None,
                "squelch_open": status[0] if status else None,
            }
        )
    settings = request.app.state.settings
    scanner = getattr(request.app.state, "health_scanner", None)
    if scanner is None:
        scanner = StorageScanner(settings.recording_path, settings.data_dir / "tonewatch.db")
        request.app.state.health_scanner = scanner
    disk = await scanner.scan()
    async with request.app.state.session_factory() as session:
        recordings = list(
            (
                await session.execute(
                    select(Call.started_at, Recording.size_bytes)
                    .join(Recording, Recording.call_id == Call.id)
                    .order_by(Call.started_at)
                )
            ).all()
        )
    forecast = storage_forecast(
        cast("int", disk.get("free_bytes", 0)), [(row[0], row[1]) for row in recordings]
    )
    outputs = []
    output_stats = (
        getattr(getattr(supervisor, "alerts", None), "output_health", {}) if supervisor else {}
    )
    for target in config.alert_targets:
        stats = output_stats.get(target.id)
        connection = None
        if isinstance(target, (MqttTarget, MeshtasticTarget)):
            publisher = getattr(getattr(supervisor, "alerts", None), "_mqtt", {}).get(target.id)
            connection = publisher.status[0] if publisher else None
        outputs.append(
            {
                "id": target.id,
                "name": target.name,
                "type": target.type,
                "last_success_at": stats.last_success_at if stats else None,
                "last_error_at": stats.last_error_at if stats else None,
                "last_error": stats.last_error if stats else None,
                "consecutive_failures": stats.consecutive_failures if stats else 0,
                "connection": connection,
            }
        )
    return {
        "generated_at": datetime.now().astimezone(),
        "sources": source_items,
        "service": {"subscribers": event_bus_health(request.app.state.bus)},
        "storage": {
            **{
                key: disk[key]
                for key in ("recordings_bytes", "free_bytes", "db_bytes", "db_wal_bytes")
                if key in disk
            },
            "retention_forecast": {"days_until_full": forecast},
        },
        "outputs": outputs,
        "cad_feeds": [
            {
                "id": feed.id,
                "name": feed.name,
                "connected": bool(
                    getattr(getattr(supervisor, "cad_health", {}).get(feed.id), "connected", False)
                ),
                "availability": getattr(
                    getattr(supervisor, "cad_health", {}).get(feed.id), "availability", None
                ),
                "last_message_at": getattr(
                    getattr(supervisor, "cad_health", {}).get(feed.id), "last_message_at", None
                ),
                "invalid_total": getattr(
                    getattr(supervisor, "cad_health", {}).get(feed.id), "invalid_total", 0
                ),
                "active_incidents": getattr(
                    getattr(supervisor, "cad_health", {}).get(feed.id), "active_incidents", 0
                ),
            }
            for feed in config.cad_feeds
        ],
        "build": {"version": __version__, "build": None, "uptime_s": time.monotonic() - _STARTED},
    }
