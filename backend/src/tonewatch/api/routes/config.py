"""Configuration resource route registration boundary."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import TypeAdapter

from tonewatch.api.deps import _dump, authenticated, collection, put, save_config, write_auth
from tonewatch.config.models import AlertTarget, AppConfig, Source, ToneSet
from tonewatch.events import CallClosed, ToneDetected

router = APIRouter(prefix="/api", tags=["configuration"])


@router.get("/tonesets", dependencies=[Depends(authenticated)])
async def tonesets(request: Request) -> list[Any]:
    return [_dump(value) for value in request.app.state.config.tone_sets]


@router.post("/tonesets", dependencies=[Depends(write_auth)], status_code=201)
async def create_toneset(request: Request, item: ToneSet) -> Any:
    return _dump((await put(request, "tone_sets", item)).tone_sets[-1])


@router.get("/tonesets/{item_id}", dependencies=[Depends(authenticated)])
async def get_toneset(request: Request, item_id: str) -> Any:
    item = next(
        (value for value in request.app.state.config.tone_sets if value.id == item_id), None
    )
    if item is None:
        raise HTTPException(404, "not found")
    return _dump(item)


@router.put("/tonesets/{item_id}", dependencies=[Depends(write_auth)])
async def update_toneset(request: Request, item_id: str, item: ToneSet) -> Any:
    if item.id != item_id:
        raise HTTPException(422, "id does not match path")
    return _dump((await put(request, "tone_sets", item)).tone_sets[-1])


@router.delete("/tonesets/{item_id}", dependencies=[Depends(write_auth)])
async def delete_toneset(request: Request, item_id: str) -> Any:
    refs = [
        value.id
        for value in request.app.state.config.sources
        if value.tonesets == "all" or item_id in value.tonesets
    ]
    refs += [
        value.id for value in request.app.state.config.tone_sets if item_id in value.alert_targets
    ]
    if refs:
        raise HTTPException(409, {"referrers": refs})
    config = AppConfig(
        tone_sets=[value for value in request.app.state.config.tone_sets if value.id != item_id],
        sources=request.app.state.config.sources,
        alert_targets=request.app.state.config.alert_targets,
    )
    return _dump(await save_config(request, config))


def _crud(path: str, kind: str, model: Any) -> None:
    @router.get(path, dependencies=[Depends(authenticated)])
    async def list_items(request: Request) -> list[Any]:
        return [_dump(value) for value in collection(request, kind)]

    @router.post(path, dependencies=[Depends(write_auth)], status_code=201)
    async def create_item(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
        item = TypeAdapter(model).validate_python(payload)
        if (
            kind == "alert_targets"
            and item.type == "script"
            and item.enabled
            and not request.app.state.settings.allow_script_targets
        ):
            raise HTTPException(403, "script targets are disabled")
        await put(request, kind, item)
        return _dump(item)

    @router.get(f"{path}/{{item_id}}", dependencies=[Depends(authenticated)])
    async def get_item(request: Request, item_id: str) -> Any:
        item = next((value for value in collection(request, kind) if value.id == item_id), None)
        if item is None:
            raise HTTPException(404, "not found")
        return _dump(item)

    @router.put(f"{path}/{{item_id}}", dependencies=[Depends(write_auth)])
    async def update_item(
        request: Request, item_id: str, payload: dict[str, Any] = Body(...)
    ) -> Any:
        if payload.get("id") != item_id:
            raise HTTPException(422, "id does not match path")
        item = TypeAdapter(model).validate_python(payload)
        if (
            kind == "alert_targets"
            and item.type == "script"
            and item.enabled
            and not request.app.state.settings.allow_script_targets
        ):
            raise HTTPException(403, "script targets are disabled")
        await put(request, kind, item)
        return _dump(item)

    @router.delete(f"{path}/{{item_id}}", dependencies=[Depends(write_auth)])
    async def delete_item(request: Request, item_id: str) -> Any:
        if not any(value.id == item_id for value in collection(request, kind)):
            raise HTTPException(404, "not found")
        values = [value for value in collection(request, kind) if value.id != item_id]
        config = AppConfig(
            tone_sets=values if kind == "tone_sets" else request.app.state.config.tone_sets,
            sources=values if kind == "sources" else request.app.state.config.sources,
            alert_targets=values
            if kind == "alert_targets"
            else request.app.state.config.alert_targets,
        )
        await save_config(request, config)
        return {"ok": True}


_crud("/sources", "sources", Source)
_crud("/alert-targets", "alert_targets", AlertTarget)


@router.post("/tonesets/{item_id}/test", dependencies=[Depends(write_auth)])
async def test_toneset(request: Request, item_id: str) -> dict[str, bool]:
    if not any(value.id == item_id for value in request.app.state.config.tone_sets):
        raise HTTPException(404, "not found")
    call_id = UUID(int=__import__("secrets").randbits(128))
    now = __import__("datetime").datetime.now().astimezone()
    request.app.state.bus.publish(ToneDetected(call_id, item_id, now, "test", True))
    request.app.state.bus.publish(CallClosed(call_id, "tested", "test", True))
    return {"ok": True}
