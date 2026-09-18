"""Authenticated data-directory backup download."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import write_auth
from tonewatch.backup import create_archive

router = APIRouter(prefix="/api/admin", tags=["admin"])
_BACKUP_RATE_LIMIT_SECONDS = 60.0


class BackupRequest(BaseModel):
    """Options for an authenticated data archive."""

    include_recordings: bool = False
    include_credentials: bool = False


@router.post("/backup", dependencies=[Depends(write_auth)])
async def backup(request: Request, options: BackupRequest) -> StreamingResponse:
    """Create and stream a temporary archive without retaining it on disk."""
    if options.include_credentials and getattr(request.state, "auth", "") == "ingress":
        raise HTTPException(403, "credential backups are not available through ingress")
    if request.app.state.maintenance_lock.locked():
        raise HTTPException(409, "maintenance operation already running")
    actor = getattr(request.state, "auth", "unknown")
    now = time.monotonic()
    last_calls: dict[str, float] | None = getattr(request.app.state, "backup_last_call", None)
    if last_calls is None:
        last_calls = {}
        request.app.state.backup_last_call = last_calls
    if now - last_calls.get(actor, 0.0) < _BACKUP_RATE_LIMIT_SECONDS:
        raise HTTPException(429, "backup rate limit exceeded")
    last_calls[actor] = now
    data_dir = request.app.state.settings.data_dir
    async with request.app.state.maintenance_lock:
        fd, name = tempfile.mkstemp(prefix=".tonewatch-backup-", suffix=".tar.gz", dir=data_dir)
        os.close(fd)
        archive_path = Path(name)
        try:
            await asyncio.to_thread(
                create_archive,
                data_dir,
                include_recordings=options.include_recordings,
                include_credentials=options.include_credentials,
                recording_root=request.app.state.settings.recording_path,
                output=archive_path,
            )
            await record_audit(
                request.app.state.session_factory,
                actor=actor,
                event_type="backup_created",
                resource="backup",
                details={
                    "include_recordings": options.include_recordings,
                    "include_credentials": options.include_credentials,
                },
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    async def body() -> Any:
        try:
            handle = await asyncio.to_thread(archive_path.open, "rb")
            try:
                while chunk := await asyncio.to_thread(handle.read, 1024 * 1024):
                    yield chunk
            finally:
                await asyncio.to_thread(handle.close)
        finally:
            archive_path.unlink(missing_ok=True)

    return StreamingResponse(
        body(),
        media_type="application/gzip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="tonewatch-backup.tar.gz"',
        },
    )
