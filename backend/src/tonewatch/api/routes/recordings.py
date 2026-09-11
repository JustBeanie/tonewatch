"""Safe database-id-only recording streaming route."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from tonewatch.api.deps import authenticated
from tonewatch.storage.models import Recording

router = APIRouter(prefix="/api", tags=["recordings"])


@router.get("/recordings/{recording_id}", dependencies=[Depends(authenticated)])
async def recording(request: Request, recording_id: int) -> Response:
    async with request.app.state.session_factory() as session:
        row = await session.get(Recording, recording_id)
        if row is None:
            raise HTTPException(404, "not found")
    root = request.app.state.settings.recording_path
    try:
        resolved = Path(row.path).resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "not found") from None
    if not resolved.is_file():
        raise HTTPException(404, "not found")
    data = resolved.read_bytes()
    total = len(data)
    start, end, status = 0, total - 1, 200
    headers = {"Accept-Ranges": "bytes"}
    value = request.headers.get("range")
    if value:
        if not value.startswith("bytes=") or "," in value:
            return Response(
                status_code=416, headers={**headers, "Content-Range": f"bytes */{total}"}
            )
        first, last = value[6:].split("-", 1) if "-" in value[6:] else ("", "")
        try:
            if first:
                start = int(first)
                end = int(last) if last else total - 1
            else:
                suffix = int(last)
                start = max(total - suffix, 0)
                end = total - 1
            if start < 0 or start >= total or end < start:
                raise ValueError
            end = min(end, total - 1)
        except (ValueError, TypeError):
            return Response(
                status_code=416, headers={**headers, "Content-Range": f"bytes */{total}"}
            )
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    media_type = {"mp3": "audio/mpeg", "ogg": "audio/ogg", "opus": "audio/ogg"}.get(
        row.format, "application/octet-stream"
    )
    return Response(
        data[start : end + 1], status_code=status, media_type=media_type, headers=headers
    )
