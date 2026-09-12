"""Authenticated API for discovered tone clusters and evidence clips."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import authenticated, write_auth
from tonewatch.config.models import ToneSet
from tonewatch.storage.models import DiscoveredTone
from tonewatch.storage.repository import get_discovered_tone, list_discovered_tones

router = APIRouter(prefix="/api", tags=["discovered-tones"])


def _dump(row: DiscoveredTone) -> dict[str, Any]:
    return {
        "id": row.id,
        "frequencies": row.mean_frequencies,
        "durations": row.median_durations,
        "count": row.count,
        "first_seen": row.first_seen.isoformat(),
        "last_seen": row.last_seen.isoformat(),
        "source_ids": row.source_ids,
        "observed_frequency_spread_pct": row.observed_frequency_spread_pct,
        "status": row.status,
        "best_clip_recording_path": row.best_clip_recording_path,
    }


@router.get("/discovered-tones", dependencies=[Depends(authenticated)])
async def discovered_tones(
    request: Request,
    source: str | None = Query(default=None),
    since: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    since_value = None
    if since:
        try:
            since_value = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(422, "invalid since") from None
        if since_value.tzinfo is None or since_value.utcoffset() is None:
            since_value = since_value.replace(tzinfo=UTC)
        else:
            since_value = since_value.astimezone(UTC)
    async with request.app.state.session_factory() as session:
        rows = await list_discovered_tones(
            session,
            source_id=source,
            since=since_value,
            status=status,
            limit=limit,
            offset=offset,
        )
    return {"items": [_dump(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/discovered-tones/{cluster_id}", dependencies=[Depends(authenticated)])
async def discovered_tone(request: Request, cluster_id: int) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        row = await get_discovered_tone(session, cluster_id)
    if row is None:
        raise HTTPException(404, "not found")
    return _dump(row)


def _slug(row: DiscoveredTone, existing: set[str]) -> str:
    base = "discovered-" + "-".join(str(round(value)) for value in row.mean_frequencies)
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


@router.post("/discovered-tones/{cluster_id}/promote", dependencies=[Depends(write_auth)])
async def promote(request: Request, cluster_id: int) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        row = await get_discovered_tone(session, cluster_id)
    if row is None:
        raise HTTPException(404, "not found")
    existing = {item.id for item in request.app.state.config.tone_sets}
    tolerance = min(5.0, max(1.5, row.observed_frequency_spread_pct * 1.5))
    draft = ToneSet.model_validate(
        {
            "id": _slug(row, existing),
            "name": (
                "Discovered " + "/".join(f"{value:g}" for value in row.mean_frequencies) + " Hz"
            ),
            "sequence": [
                {"freq_hz": frequency, "tol_pct": tolerance, "min_s": duration * 0.8}
                for frequency, duration in zip(
                    row.mean_frequencies, row.median_durations, strict=True
                )
            ],
        }
    )
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="discovered_tone_promote",
        resource=str(cluster_id),
    )
    return draft.model_dump(mode="json")


@router.post("/discovered-tones/{cluster_id}/dismiss", dependencies=[Depends(write_auth)])
async def dismiss(request: Request, cluster_id: int) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        row = await get_discovered_tone(session, cluster_id)
        if row is None:
            raise HTTPException(404, "not found")
        row.status = "dismissed"
        await session.commit()
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="discovered_tone_dismiss",
        resource=str(cluster_id),
    )
    return {"ok": True}


@router.delete("/discovered-tones/{cluster_id}", dependencies=[Depends(write_auth)])
async def delete_discovered_tone(request: Request, cluster_id: int) -> dict[str, bool]:
    async with request.app.state.session_factory() as session:
        row = await get_discovered_tone(session, cluster_id)
        if row is None:
            raise HTTPException(404, "not found")
        clip = Path(row.best_clip_recording_path) if row.best_clip_recording_path else None
        if clip is not None:
            try:
                safe = _safe_clip(request, clip, cluster_id)
            except (FileNotFoundError, OSError, ValueError):
                # A missing or foreign path never gets unlinked; the row is
                # still removed so retention cannot make it undeletable.
                safe = None
            if safe is not None:
                safe.unlink(missing_ok=True)
        await session.execute(delete(DiscoveredTone).where(DiscoveredTone.id == cluster_id))
        await session.commit()
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="discovered_tone_delete",
        resource=str(cluster_id),
    )
    return {"ok": True}


def _safe_clip(request: Request, path: Path, cluster_id: int) -> Path:
    root = request.app.state.settings.recording_path.resolve()
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    expected = root / "discovered" / f"{cluster_id}.mp3"
    if not resolved.is_file() or resolved != expected:
        raise ValueError("invalid clip path")
    return resolved


@router.get("/discovered-tones/{cluster_id}/clip", dependencies=[Depends(authenticated)])
async def discovered_clip(request: Request, cluster_id: int) -> Response:
    async with request.app.state.session_factory() as session:
        row = await get_discovered_tone(session, cluster_id)
    if row is None or not row.best_clip_recording_path:
        raise HTTPException(404, "not found")
    try:
        path = _safe_clip(request, Path(row.best_clip_recording_path), cluster_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "not found") from None
    data = path.read_bytes()
    total = len(data)
    start, end, code = 0, total - 1, 200
    headers = {"Accept-Ranges": "bytes"}
    value = request.headers.get("range")
    if value:
        try:
            if not value.startswith("bytes=") or "," in value:
                raise ValueError
            first, last = value[6:].split("-", 1)
            if first:
                start, end = int(first), int(last) if last else total - 1
            else:
                start, end = max(total - int(last), 0), total - 1
            if start < 0 or start >= total or end < start:
                raise ValueError
            end = min(end, total - 1)
            code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        except ValueError:
            return Response(
                status_code=416,
                headers={**headers, "Content-Range": f"bytes */{total}"},
            )
    return Response(
        data[start : end + 1], status_code=code, media_type="audio/mpeg", headers=headers
    )
