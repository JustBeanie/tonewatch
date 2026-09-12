"""Authenticated TTD import preview and apply endpoint."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import save_config, write_auth
from tonewatch.importers.ttd import TTD_MAX_BYTES, TtdImportError, apply_import, parse_ttd

router = APIRouter(prefix="/api", tags=["import"])


async def _request_text(request: Request) -> str:
    """Read either an uploaded file part or a raw UTF-8 request body."""
    if request.headers.get("content-type", "").casefold().startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "multipart upload must contain a file field")
        try:
            raw = await upload.read(TTD_MAX_BYTES + 1)
        finally:
            await upload.close()
    else:
        raw = await request.body()
    if len(raw) > TTD_MAX_BYTES:
        raise HTTPException(413, "TTD config exceeds the 256 KiB limit")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "TTD config must be UTF-8 text") from exc


@router.post("/import/ttd/", include_in_schema=False, dependencies=[Depends(write_auth)])
@router.post("/import/ttd", dependencies=[Depends(write_auth)])
async def import_ttd(
    request: Request,
    apply: bool = False,
    mode: Literal["merge", "replace"] = "merge",
) -> dict[str, object]:
    """Preview or atomically apply a TTD tone-set import."""
    try:
        result = parse_ttd(await _request_text(request))
    except TtdImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = result.as_dict()
    payload["applied"] = False
    if apply and result.tone_sets:
        try:
            config = apply_import(request.app.state.config, result, mode)
        except TtdImportError as exc:
            raise HTTPException(422, str(exc)) from exc
        await save_config(request, config, audit=False)
        await record_audit(
            request.app.state.session_factory,
            actor=getattr(request.state, "auth", "unknown"),
            event_type="ttd_import",
            resource="config",
            details={
                "imported": result.imported_count,
                "skipped": result.skipped_count,
                "mode": mode,
            },
        )
        payload["applied"] = True
    return payload
