"""Owner credential-management endpoints."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from tonewatch.api.audit import record_audit
from tonewatch.api.auth import atomic_write_secret, verify_password
from tonewatch.api.deps import credential_write_auth
from tonewatch.streaming.live import live_secret_path

router = APIRouter(prefix="/api/admin/credentials", tags=["admin-credentials"])


def _private(response: JSONResponse) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/api-token/rotate", dependencies=[Depends(credential_write_auth)])
async def rotate_api_token(request: Request) -> JSONResponse:
    body = await request.json()
    grace = body.get("grace_seconds", 3600) if isinstance(body, dict) else 3600
    if not isinstance(grace, int) or isinstance(grace, bool) or not 0 <= grace <= 86400:
        raise HTTPException(422, "grace_seconds must be between 0 and 86400")
    token, valid_until = request.app.state.auth.rotate_api_token(grace)
    await record_audit(
        request.app.state.session_factory,
        actor=request.state.auth,
        event_type="api_token_rotated",
        resource="api_token",
        details={"grace_seconds": grace},
    )
    return _private(JSONResponse({"token": token, "previous_valid_until": valid_until}))


@router.post("/live-secret/rotate", dependencies=[Depends(credential_write_auth)])
async def rotate_live_secret(request: Request) -> JSONResponse:
    path = live_secret_path(request.app.state.settings.data_dir)
    secret = secrets.token_bytes(32)
    atomic_write_secret(path, secret)
    request.app.state.live_hub.close_all()
    await record_audit(
        request.app.state.session_factory,
        actor=request.state.auth,
        event_type="live_secret_rotated",
        resource="live_stream",
    )
    return _private(JSONResponse({"ok": True}))


@router.post("/ui-password", dependencies=[Depends(credential_write_auth)])
async def change_ui_password(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("new_password"), str):
        raise HTTPException(422, "new_password is required")
    new = body["new_password"]
    if len(new) < 12:
        raise HTTPException(422, "new_password must be at least 12 characters")
    auth = request.app.state.auth
    ip = request.client.host if request.client else "unknown"
    if not auth.password_attempt_allowed(ip):
        raise HTTPException(429, "too many password attempts")
    current = body.get("current_password")
    if auth.password_hash is None:
        if request.state.auth != "bearer" or current not in (None, ""):
            raise HTTPException(403, "current password is required")
    elif not isinstance(current, str) or not verify_password(current, auth.password_hash):
        auth.record_password_failure(ip)
        await record_audit(
            request.app.state.session_factory,
            actor=request.state.auth,
            event_type="ui_password_change_failed",
            resource="ui_password",
            details={"status": 403},
        )
        raise HTTPException(403, "current password is incorrect")
    sid = request.cookies.get("tonewatch_session") if request.state.auth == "session" else None
    auth.clear_password_failures(ip)
    auth.change_password(new)
    auth.revoke_sessions(sid)
    await record_audit(
        request.app.state.session_factory,
        actor=request.state.auth,
        event_type="ui_password_changed",
        resource="ui_password",
    )
    return _private(JSONResponse({"ok": True}))


@router.post("/sessions/revoke-all", dependencies=[Depends(credential_write_auth)])
async def revoke_all_sessions(request: Request) -> JSONResponse:
    request.app.state.auth.sessions.clear()
    await record_audit(
        request.app.state.session_factory,
        actor=request.state.auth,
        event_type="sessions_revoked",
        resource="sessions",
    )
    return _private(JSONResponse({"ok": True}))
