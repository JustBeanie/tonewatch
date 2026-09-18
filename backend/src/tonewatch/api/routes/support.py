"""Support bundle and in-memory log viewer endpoints."""

from __future__ import annotations

import hashlib
import io
import json
import ntpath
import platform
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tonewatch import __version__
from tonewatch.api.audit import is_secret_key, mask_secrets, record_audit
from tonewatch.api.deps import authenticated, write_auth
from tonewatch.api.routes.admin import health
from tonewatch.logging import active_log_ring
from tonewatch.storage.models import Call

router = APIRouter(prefix="/api/admin", tags=["admin"])
_BUNDLE_MAX_BYTES = 4 * 1024 * 1024

_BUNDLE_URL = re.compile(r"(?P<url>(?:https?|rtsps?|mqtt|wss?)://[^\s\"'<>]+)")


def _config_strings(value: Any, *, key: str = "") -> set[str]:
    if isinstance(value, dict):
        result: set[str] = set()
        for name, item in value.items():
            result.update(_config_strings(item, key=str(name)))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_config_strings(item, key=key))
        return result
    if isinstance(value, str) and (
        is_secret_key(key)
        or key.casefold() in {"username", "host", "broker", "url", "path", "tile_url"}
    ):
        return {value}
    return set()


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED URL]"
    if not parsed.scheme or not parsed.netloc:
        return value
    return f"{parsed.scheme.lower()}://[host]/…"


def _scrub_string(value: str, *, key: str, secrets: set[str], roots: tuple[str, ...]) -> str:
    normalized = key.casefold()
    if is_secret_key(key) or normalized in {"psk", "api_key", "private_key", "username"}:
        return "[REDACTED]" if value else value
    if normalized in {"path", "file", "recording_path"}:
        return ntpath.basename(value.replace("/", "\\"))
    for secret in sorted(secrets, key=len, reverse=True):
        if secret and secret in value:
            value = value.replace(secret, "[REDACTED]")
    for root in roots:
        if root:
            value = value.replace(root, "[REDACTED]").replace(root.replace("\\", "/"), "[REDACTED]")
    if "://" in value:
        value = _BUNDLE_URL.sub(lambda match: _safe_url(match.group("url")), value)
    return value


def _bundle_safe(
    value: Any,
    *,
    key: str = "",
    secrets: set[str] | None = None,
    roots: tuple[str, ...] = (),
) -> Any:
    normalized = key.casefold()
    secrets = secrets or set()
    if normalized in {"address", "addresses", "cross_streets", "incident_text", "notes"}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(name): _bundle_safe(item, key=str(name), secrets=secrets, roots=roots)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_bundle_safe(item, key=key, secrets=secrets, roots=roots) for item in value]
    if isinstance(value, str):
        return _scrub_string(value, key=key, secrets=secrets, roots=roots)
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _zip_bundle(files: dict[str, bytes]) -> bytes:
    manifest_files = [
        {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        for name, content in files.items()
    ]
    manifest = _json_bytes(
        {
            "generated_at": datetime.now().astimezone().isoformat(),
            "version": __version__,
            "files": manifest_files,
        }
    )
    files = {"manifest.json": manifest, **files}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    if output.tell() > _BUNDLE_MAX_BYTES:
        raise HTTPException(413, "support bundle too large")
    return output.getvalue()


@router.get("/logs", dependencies=[Depends(authenticated)])
async def logs(
    request: Request,
    level: str = Query("INFO"),
    since_seq: int | None = Query(None, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, object]:
    ring = active_log_ring()
    if ring is None:
        return {"items": []}
    try:
        items = ring.records(level=level, since_seq=since_seq, limit=limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"items": items}


@router.post("/support-bundle", dependencies=[Depends(write_auth)])
async def support_bundle(request: Request) -> StreamingResponse:
    now = time.monotonic()
    last = getattr(request.app.state, "support_bundle_last", 0.0)
    if now - last < 30:
        raise HTTPException(429, "support bundle rate limit")
    request.app.state.support_bundle_last = now

    raw_config = request.app.state.config.model_dump(mode="json")
    secrets = _config_strings(raw_config)
    holder = getattr(request.app.state.auth, "secret_holder", None)
    if holder is not None:
        secrets.update(token for token in (holder.current, holder.previous) if token)
    roots = (str(request.app.state.settings.data_dir), str(Path.home()))
    config = _bundle_safe(mask_secrets(raw_config), secrets=secrets, roots=roots)
    health_body = _bundle_safe(await health(request), secrets=secrets, roots=roots)
    ring = active_log_ring()
    log_rows = (
        _bundle_safe(ring.records(limit=2000), secrets=secrets, roots=roots)
        if ring is not None
        else []
    )
    detections: list[dict[str, object]] = []
    async with request.app.state.session_factory() as session:
        calls = list(
            (
                await session.execute(
                    select(Call)
                    .options(
                        selectinload(Call.tone_sets),
                        selectinload(Call.recordings),
                        selectinload(Call.alerts),
                    )
                    .order_by(Call.started_at.desc())
                    .limit(50)
                )
            ).scalars()
        )
        detections.extend(
            {
                "time": call.started_at,
                "tone_set_ids": [tone.toneset_id for tone in call.tone_sets],
                "duration_s": sum(recording.duration_s for recording in call.recordings),
                "outcome_counts": {
                    "ok": sum(1 for attempt in call.alerts if attempt.ok),
                    "failed": sum(1 for attempt in call.alerts if not attempt.ok),
                },
            }
            for call in calls
        )
    detections = _bundle_safe(detections, secrets=secrets, roots=roots)
    environment = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "packages": {"tonewatch": __version__},
        "mode": {
            "addon": bool(request.app.state.settings.addon_mode),
            "windows": sys.platform == "win32",
            "docker": Path("/.dockerenv").is_file(),
        },
    }
    environment = _bundle_safe(environment, secrets=secrets, roots=roots)
    files = {
        "config.redacted.yaml": yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
        "health.json": _json_bytes(health_body),
        "logs.jsonl": b"".join(_json_bytes(row) + b"\n" for row in log_rows),
        "detections.json": _json_bytes(detections),
        "environment.json": _json_bytes(environment),
    }
    payload = _zip_bundle(files)
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="support_bundle_created",
        resource="support-bundle",
        details={"file_count": len(files), "bytes": len(payload)},
    )
    response = StreamingResponse(iter([payload]), media_type="application/zip")
    response.headers["Content-Disposition"] = "attachment; filename=tonewatch-support.zip"
    response.headers["Cache-Control"] = "no-store"
    return response
