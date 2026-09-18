"""Authenticated administrative health and alert-delivery endpoints."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from tonewatch import __version__
from tonewatch.admin.health import StorageScanner, event_bus_health, storage_forecast
from tonewatch.api.audit import SecretRestoreError, mask_secrets, record_audit, restore_secrets
from tonewatch.api.deps import authenticated, save_config, write_auth
from tonewatch.config.history import ConfigHistory, HistoryError, structured_diff
from tonewatch.config.models import AppConfig, MeshtasticTarget, MqttTarget
from tonewatch.pipeline.drill import build_waveform
from tonewatch.storage.models import Call, Recording
from tonewatch.storage.repository import list_alert_attempts

router = APIRouter(prefix="/api/admin", tags=["admin"])
_STARTED = time.monotonic()
_CONFIG_IMPORT_MAX_BYTES = 256 * 1024


class ConfigExportRequest(BaseModel):
    """Options for an authenticated configuration export."""

    format: Literal["yaml", "json"] = "yaml"
    include_secrets: bool = False
    confirm: str | None = None


class DrillRequest(BaseModel):
    source_id: str
    toneset_id: str
    mode: Literal["mix", "replace"] = "replace"
    voice_s: float = Field(default=5.0, ge=0, le=20)
    keep: bool = False


@router.post("/drill", status_code=202, dependencies=[Depends(write_auth)])
async def start_drill(request: Request, body: DrillRequest) -> JSONResponse:
    """Inject a marked synthetic page into one already-running channel."""
    if getattr(request.state, "auth", None) == "ingress":
        raise HTTPException(403, "drills are not available through ingress")
    config = request.app.state.config
    source = next((item for item in config.sources if item.id == body.source_id), None)
    if source is None:
        raise HTTPException(404, "source not found")
    if not source.enabled:
        raise HTTPException(409, "source is disabled")
    toneset = next((item for item in config.tone_sets if item.id == body.toneset_id), None)
    if toneset is None:
        raise HTTPException(404, "tone set not found")
    if not toneset.enabled:
        raise HTTPException(409, "tone set is disabled")
    supervisor = request.app.state.supervisor
    channel = supervisor.channel_for(body.source_id) if supervisor is not None else None
    if channel is None:
        raise HTTPException(409, "source is not running")
    now = time.monotonic()
    active: set[str] = getattr(supervisor, "_drill_active_sources", set())
    if body.source_id in active or channel.drill_active:
        raise HTTPException(429, "a drill is already active for this source")
    last = getattr(supervisor, "_drill_last_started", 0.0)
    if now - last < 60:
        raise HTTPException(429, "drills are rate limited globally")
    waveform = build_waveform(
        [(item.freq_hz, item.min_s, item.max_s or item.min_s) for item in toneset.sequence],
        voice_s=body.voice_s,
    )
    try:
        drill_id, duration = await channel.start_drill(waveform.samples, body.mode, body.keep)
    except RuntimeError as exc:
        raise HTTPException(429, str(exc)) from exc
    active.add(body.source_id)
    supervisor._drill_active_sources = active
    supervisor._drill_last_started = now
    asyncio_task = asyncio.create_task(
        _release_drill(supervisor, body.source_id, duration), name=f"tonewatch-drill-{drill_id}"
    )
    drill_tasks: set[asyncio.Task[None]] = getattr(supervisor, "_drill_tasks", set())
    drill_tasks.add(asyncio_task)
    supervisor._drill_tasks = drill_tasks
    asyncio_task.add_done_callback(drill_tasks.discard)
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="drill_started",
        resource=str(drill_id),
        details={
            "source_id": body.source_id,
            "toneset_id": body.toneset_id,
            "mode": body.mode,
            "keep": body.keep,
        },
    )
    return JSONResponse(
        {"drill_id": str(drill_id), "expected_duration_s": duration}, status_code=202
    )


async def _release_drill(supervisor: Any, source_id: str, duration: float) -> None:
    try:
        await asyncio.sleep(duration)
    finally:
        getattr(supervisor, "_drill_active_sources", set()).discard(source_id)


def _history(request: Request) -> ConfigHistory:
    return ConfigHistory(request.app.state.settings.data_dir)


def _history_error(exc: HistoryError) -> HTTPException:
    return HTTPException(404, str(exc))


def _require_if_match(request: Request) -> None:
    if not request.headers.get("if-match"):
        raise HTTPException(428, "If-Match is required for this configuration write")


def _parse_config_body(raw: bytes) -> dict[str, Any]:
    if len(raw) > _CONFIG_IMPORT_MAX_BYTES:
        raise HTTPException(413, "configuration input exceeds the 256 KiB limit")
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"invalid YAML/JSON configuration: {exc}") from None
    if not isinstance(value, dict):
        raise HTTPException(422, "configuration must be an object")
    try:
        return dict(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "configuration must be an object") from exc


async def _validated_import(request: Request) -> AppConfig:
    submitted = _parse_config_body(await request.body())
    try:
        restored = restore_secrets(request.app.state.config.model_dump(mode="python"), submitted)
        return AppConfig.model_validate(restored)
    except (SecretRestoreError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/config/versions", dependencies=[Depends(authenticated)])
async def config_versions(request: Request) -> list[dict[str, Any]]:
    return _history(request).list_versions()


@router.get("/config/versions/{version_id}", dependencies=[Depends(authenticated)])
async def config_version(request: Request, version_id: str) -> dict[str, Any]:
    try:
        return _history(request).masked_content(version_id)
    except HistoryError as exc:
        raise _history_error(exc) from None


@router.get("/config/versions/{version_id}/diff", dependencies=[Depends(authenticated)])
async def config_version_diff(
    request: Request, version_id: str, against: str = Query("current")
) -> list[dict[str, Any]]:
    history = _history(request)
    try:
        before = history.raw_config(version_id)
        if against == "current":
            after = request.app.state.config.model_dump(mode="json")
            return structured_diff(before, after)
        return history.diff(version_id, against)
    except HistoryError as exc:
        raise _history_error(exc) from None


@router.post("/config/versions/{version_id}/rollback", dependencies=[Depends(write_auth)])
async def rollback_config(request: Request, version_id: str) -> Response:
    _require_if_match(request)
    try:
        config = _history(request).config(version_id)
    except HistoryError as exc:
        raise HTTPException(422, str(exc)) from None
    saved = await save_config(request, config)
    return Response(
        content=json.dumps(mask_secrets(saved.model_dump(mode="json"))),
        media_type="application/json",
        headers={"ETag": request.app.state.store.etag()},
    )


def _export_response(
    config: AppConfig, *, format_: Literal["yaml", "json"], include_secrets: bool
) -> Response:
    value = config.model_dump(mode="json")
    if not include_secrets:
        value = mask_secrets(value)
    body = (
        json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        if format_ == "json"
        else yaml.safe_dump(value, sort_keys=False).encode("utf-8")
    )
    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="tonewatch-config.{format_}"',
    }
    return Response(
        content=body,
        media_type="application/json" if format_ == "json" else "application/yaml",
        headers=headers,
    )


async def _export_config(request: Request, options: ConfigExportRequest) -> Response:
    if options.include_secrets:
        if getattr(request.state, "auth", "") == "ingress":
            raise HTTPException(403, "secret export is not available through ingress")
        if options.confirm != "include-secrets":
            raise HTTPException(422, "confirm=include-secrets is required")
    response = _export_response(
        request.app.state.config,
        format_=options.format,
        include_secrets=options.include_secrets,
    )
    if options.include_secrets:
        response.headers["Warning"] = '299 ToneWatch "configuration contains plaintext secrets"'
        await record_audit(
            request.app.state.session_factory,
            actor=getattr(request.state, "auth", "unknown"),
            event_type="config_export_secrets",
            resource="config",
        )
    return response


@router.get("/config/export", dependencies=[Depends(authenticated)])
async def export_config(
    request: Request,
    format_: Literal["yaml", "json"] = Query("yaml", alias="format"),
    include_secrets: bool = False,
    confirm: str | None = None,
) -> Response:
    if include_secrets:
        raise HTTPException(422, "secret export requires POST")
    return await _export_config(
        request,
        ConfigExportRequest(format=format_, include_secrets=False, confirm=confirm),
    )


@router.post("/config/export", dependencies=[Depends(write_auth)])
async def export_config_post(request: Request, options: ConfigExportRequest) -> Response:
    return await _export_config(request, options)


@router.post("/config/import/preview", dependencies=[Depends(write_auth)])
async def preview_config_import(request: Request) -> dict[str, Any]:
    config = await _validated_import(request)
    return {
        "applied": False,
        "diff": structured_diff(
            request.app.state.config.model_dump(mode="json"), config.model_dump(mode="json")
        ),
    }


@router.post("/config/import/apply", dependencies=[Depends(write_auth)])
async def apply_config_import(request: Request) -> Response:
    _require_if_match(request)
    config = await _validated_import(request)
    saved = await save_config(request, config)
    return Response(
        content=json.dumps(mask_secrets(saved.model_dump(mode="json"))),
        media_type="application/json",
        headers={"ETag": request.app.state.store.etag()},
    )


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
