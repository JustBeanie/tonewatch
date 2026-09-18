"""Authenticated maintenance operations."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select

from tonewatch.admin.counters import METRICS_COUNTERS
from tonewatch.api.audit import record_audit
from tonewatch.api.deps import write_auth
from tonewatch.api.metrics import render_metrics
from tonewatch.recording.retention import RetentionService, safe_recording_path, scan_orphans
from tonewatch.storage.db import (
    DatabaseCheckpointTimeoutError,
    checkpoint_database,
    vacuum_database,
)
from tonewatch.storage.models import Recording

router = APIRouter(tags=["maintenance"])


def _busy(request: Request) -> None:
    if request.app.state.maintenance_lock.locked():
        raise HTTPException(409, "maintenance operation already running")


async def _audit(request: Request, event_type: str, resource: str, details: dict[str, Any]) -> None:
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type=event_type,
        resource=resource,
        details=details,
    )


async def _retention(request: Request, apply: bool) -> dict[str, object]:
    _busy(request)
    async with request.app.state.maintenance_lock:
        service: RetentionService = request.app.state.retention_service
        async with request.app.state.session_factory() as session:
            plan = await service.plan(session)
            result = await service.apply(session, plan) if apply else plan.counts
        await _audit(
            request, "retention_run" if apply else "retention_preview", "retention", result
        )
        return result


@router.post("/api/admin/maintenance/retention/preview", dependencies=[Depends(write_auth)])
async def retention_preview(request: Request) -> dict[str, object]:
    return await _retention(request, False)


@router.post("/api/admin/maintenance/retention/run", dependencies=[Depends(write_auth)])
async def retention_run(request: Request) -> dict[str, object]:
    return await _retention(request, True)


async def _database_action(request: Request, action: str) -> dict[str, int]:
    _busy(request)
    async with request.app.state.maintenance_lock:
        path = request.app.state.settings.data_dir / "tonewatch.db"
        if action == "checkpoint":
            before = path.stat().st_size
            try:
                await asyncio.to_thread(checkpoint_database, path)
            except DatabaseCheckpointTimeoutError as exc:
                raise HTTPException(409, "database is busy") from exc
            result = {"before_bytes": before, "after_bytes": path.stat().st_size}
        else:
            try:
                before, after = await asyncio.to_thread(vacuum_database, path)
            except DatabaseCheckpointTimeoutError as exc:
                raise HTTPException(409, "database is busy") from exc
            result = {"before_bytes": before, "after_bytes": after}
        await _audit(request, f"database_{action}", "database", result)
        return result


@router.post("/api/admin/maintenance/database/checkpoint", dependencies=[Depends(write_auth)])
async def checkpoint(request: Request) -> dict[str, int]:
    return await _database_action(request, "checkpoint")


@router.post("/api/admin/maintenance/database/vacuum", dependencies=[Depends(write_auth)])
async def vacuum(request: Request) -> dict[str, int]:
    return await _database_action(request, "vacuum")


class OrphanApply(BaseModel):
    delete_files: bool = False
    delete_rows: bool = False
    expected_counts: dict[str, int]


@router.post("/api/admin/maintenance/orphans/preview", dependencies=[Depends(write_auth)])
async def orphan_preview(request: Request) -> dict[str, object]:
    root = request.app.state.settings.recording_path.resolve()
    async with request.app.state.session_factory() as session:
        rows = list((await session.scalars(select(Recording))).all())
        scan = scan_orphans(
            root,
            rows,
            time.time(),
            request.app.state.settings.retention.orphan_safety_age_seconds,
        )
    result: dict[str, object] = {
        "files": [
            {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
            for path in scan.files[:1000]
        ],
        "missing_rows": [
            {
                "id": row.id,
                "path": safe_recording_path(root, Path(row.path)).relative_to(root).as_posix(),
            }
            for row in scan.missing_rows[:1000]
        ],
        "invalid_rows": [{"id": row_id} for row_id in scan.invalid_row_ids[:1000]],
        "file_count": scan.file_count,
        "row_count": len(scan.missing_rows),
        "bytes": scan.file_bytes,
    }
    await _audit(
        request,
        "orphans_preview",
        "orphans",
        {"file_count": result["file_count"], "row_count": result["row_count"]},
    )
    return result


@router.post("/api/admin/maintenance/orphans/apply", dependencies=[Depends(write_auth)])
async def orphan_apply(request: Request, body: OrphanApply) -> dict[str, object]:
    _busy(request)
    async with request.app.state.maintenance_lock:
        root = request.app.state.settings.recording_path.resolve()
        async with request.app.state.session_factory() as session:
            rows = list((await session.scalars(select(Recording))).all())
            scan = scan_orphans(
                root,
                rows,
                time.time(),
                request.app.state.settings.retention.orphan_safety_age_seconds,
            )
            actual = {"file_count": scan.file_count, "row_count": len(scan.missing_rows)}
            if any(body.expected_counts.get(key) != value for key, value in actual.items()):
                raise HTTPException(409, "orphan counts changed")
            live_rows = list((await session.scalars(select(Recording))).all())
            live_paths: set[Path] = set()
            for row in live_rows:
                try:
                    live_paths.add(safe_recording_path(root, Path(row.path)))
                except ValueError:
                    continue
            safety_age = request.app.state.settings.retention.orphan_safety_age_seconds
            cutoff = time.time() - safety_age
            if body.delete_files:
                for path in scan.files:
                    if path in live_paths or path.is_symlink() or path.stat().st_mtime > cutoff:
                        raise HTTPException(409, "orphan candidates changed")
                    safe_recording_path(root, path).unlink(missing_ok=True)
            if body.delete_rows:
                for row in scan.missing_rows:
                    created_at = row.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=UTC)
                    if created_at.timestamp() > time.time() - safety_age:
                        raise HTTPException(409, "orphan candidates changed")
                    await session.delete(row)
            await session.commit()
        result: dict[str, object] = {
            "deleted_files": len(scan.files) if body.delete_files else 0,
            "deleted_rows": len(scan.missing_rows) if body.delete_rows else 0,
            "invalid_rows": [{"id": row_id} for row_id in scan.invalid_row_ids[:1000]],
        }
        await _audit(request, "orphans_apply", "orphans", result)
        return result


@router.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    settings = request.app.state.settings
    if not settings.metrics.enabled:
        raise HTTPException(404, "not found")
    if not request.app.state.auth.bearer_valid(request):
        raise HTTPException(401, "authentication required")
    from tonewatch.api.routes.admin import health

    snapshot = await health(request)
    config = request.app.state.config
    body = render_metrics(
        snapshot,
        configured_source_ids=(item.id for item in config.sources),
        configured_target_ids=(item.id for item in config.alert_targets),
        configured_toneset_ids=(item.id for item in config.tone_sets),
        configured_feed_ids=(item.id for item in config.cad_feeds),
        version=str(cast("dict[str, object]", snapshot.get("build", {})).get("version", "unknown")),
        detections=dict(METRICS_COUNTERS.detections),
        alert_attempts=dict(METRICS_COUNTERS.alert_attempts),
    )
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
