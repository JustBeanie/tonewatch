"""Authenticated live MP3 URL issuance and streaming."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import base_path, write_auth
from tonewatch.config.models import Source
from tonewatch.streaming.live import LiveHub, make_live_token, verify_live_token

router = APIRouter(prefix="/api", tags=["live"])


def _source(request: Request, source_id: str) -> Source:
    source = next((item for item in request.app.state.config.sources if item.id == source_id), None)
    if (
        source is None
        or not request.app.state.config.live_stream.enabled
        or not source.live_stream_enabled
    ):
        raise HTTPException(404, "not found")
    return source


@router.post("/sources/{source_id}/live-url", dependencies=[Depends(write_auth)])
async def issue_live_url(
    request: Request, source_id: str, external: bool = False
) -> dict[str, Any]:
    _source(request, source_id)
    live = request.app.state.config.live_stream
    hub: LiveHub = request.app.state.live_hub
    if hub.listener_count >= live.max_listeners_total:
        raise HTTPException(503, "live listener capacity reached")
    expires_at = int(time.time()) + live.token_ttl_s
    token = make_live_token(request.app.state.settings.data_dir, source_id, expires_at)
    relative = f"/api/sources/{source_id}/live.mp3?t={token}"
    public_base = request.app.state.settings.public_base_url if external else None
    url = f"{public_base}{relative}" if public_base else f"{base_path(request)}{relative}"
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="live_url_issued",
        resource=source_id,
        details={"source_id": source_id, "expires_at": expires_at},
    )
    return {"url": url, "expires_at": expires_at}


@router.get("/sources/{source_id}/live.mp3")
@router.head("/sources/{source_id}/live.mp3")
async def live_mp3(request: Request, source_id: str, t: str | None = None) -> Response:
    _source(request, source_id)
    if t is None:
        request.app.state.auth.authorize(request)
    elif not verify_live_token(request.app.state.settings.data_dir, source_id, t):
        raise HTTPException(401, "authentication required")
    headers = {"Cache-Control": "no-store", "Accept-Ranges": "none"}
    if request.method == "HEAD":
        return Response(media_type="audio/mpeg", headers=headers)
    live = request.app.state.config.live_stream
    hub: LiveHub = request.app.state.live_hub
    if (
        hub.listeners_for(source_id) >= live.max_listeners_per_source
        or hub.listener_count >= live.max_listeners_total
    ):
        raise HTTPException(503, "live listener capacity reached")
    listener = hub.add_listener(source_id)

    async def body() -> AsyncIterator[bytes]:
        try:
            while not await request.is_disconnected():
                chunk = await listener.get()
                if not chunk:
                    return
                yield chunk
        finally:
            hub.remove_listener(listener)

    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers=headers,
    )
