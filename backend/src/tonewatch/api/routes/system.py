"""Liveness, readiness, and device routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from tonewatch.api.deps import authenticated

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    ready = bool(request.app.state.ready)
    return JSONResponse({"ok": ready}, status_code=200 if ready else 503)


@router.get("/api/devices", dependencies=[Depends(authenticated)])
async def devices() -> list[dict[str, Any]]:
    from tonewatch.api.app import input_devices

    return input_devices()
