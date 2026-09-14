"""Configuration resource route registration boundary."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from tonewatch.api.deps import _dump, authenticated, collection, put, save_config, write_auth
from tonewatch.config.models import AlertTarget, AppConfig, Source, ToneSet
from tonewatch.config.store import replace_config as rebuild_config
from tonewatch.events import CallClosed, ToneDetected
from tonewatch.storage.models import DiscoveredTone

router = APIRouter(prefix="/api", tags=["configuration"])


@router.get("/config", dependencies=[Depends(authenticated)])
async def get_config(request: Request) -> JSONResponse:
    return JSONResponse(
        _dump(request.app.state.config), headers={"ETag": request.app.state.store.etag()}
    )


@router.put("/config", dependencies=[Depends(write_auth)])
async def replace_config(request: Request, config: AppConfig) -> JSONResponse:
    saved = await save_config(request, config)
    return JSONResponse(_dump(saved), headers={"ETag": request.app.state.store.etag()})


@router.get("/tonesets", dependencies=[Depends(authenticated)])
async def tonesets(request: Request) -> list[Any]:
    return [_dump(value) for value in request.app.state.config.tone_sets]


@router.post("/tonesets", dependencies=[Depends(write_auth)], status_code=201)
async def create_toneset(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
    discovered_id = payload.pop("discovered_tone_id", None)
    try:
        item = ToneSet.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    result = _dump((await put(request, "tone_sets", item)).tone_sets[-1])
    if discovered_id is not None:
        try:
            discovered_id = int(discovered_id)
        except (TypeError, ValueError):
            raise HTTPException(422, "invalid discovered_tone_id") from None
        async with request.app.state.session_factory() as session:
            row = await session.get(DiscoveredTone, discovered_id)
            if row is None:
                raise HTTPException(404, "discovered tone not found")
            row.status = "promoted"
            await session.commit()
    return result


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
    config = rebuild_config(
        request.app.state.config,
        tone_sets=[value for value in request.app.state.config.tone_sets if value.id != item_id],
    )
    return _dump(await save_config(request, config))


def _crud(path: str, kind: str, model: Any) -> None:
    @router.get(path, dependencies=[Depends(authenticated)])
    async def list_items(request: Request) -> list[Any]:
        values = []
        for value in collection(request, kind):
            item = _dump(value)
            if kind == "sources":
                supervisor = getattr(request.app.state, "supervisor", None)
                status = (
                    supervisor.source_status(value.id) if supervisor is not None else (None, None)
                )
                open_state, last_activity = status
                item["squelch_open"] = open_state
                item["last_activity_at"] = last_activity
                live_hub = getattr(request.app.state, "live_hub", None)
                item["live_listeners"] = (
                    live_hub.listeners_for(value.id) if live_hub is not None else None
                )
            values.append(item)
        return values

    @router.post(path, dependencies=[Depends(write_auth)], status_code=201)
    async def create_item(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
        try:
            item = TypeAdapter(model).validate_python(payload)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
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
        result = _dump(item)
        if kind == "sources":
            supervisor = getattr(request.app.state, "supervisor", None)
            status = supervisor.source_status(item.id) if supervisor is not None else (None, None)
            open_state, last_activity = status
            result["squelch_open"] = open_state
            result["last_activity_at"] = last_activity
            live_hub = getattr(request.app.state, "live_hub", None)
            result["live_listeners"] = (
                live_hub.listeners_for(item_id) if live_hub is not None else None
            )
        return result

    @router.put(f"{path}/{{item_id}}", dependencies=[Depends(write_auth)])
    async def update_item(
        request: Request, item_id: str, payload: dict[str, Any] = Body(...)
    ) -> Any:
        if payload.get("id") != item_id:
            raise HTTPException(422, "id does not match path")
        try:
            item = TypeAdapter(model).validate_python(payload)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
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
        config = rebuild_config(request.app.state.config, **{kind: values})
        await save_config(request, config)
        return {"ok": True}


_crud("/sources", "sources", Source)
_crud("/alert-targets", "alert_targets", AlertTarget)


@router.get("/map-config", dependencies=[Depends(authenticated)])
async def get_map_config(request: Request) -> dict[str, Any]:
    """Return the active map policy and the opt-in OSM preset."""
    from tonewatch.config.models import OSM_MAP_PRESET

    return {"map": _dump(request.app.state.config.map), "osm_preset": _dump(OSM_MAP_PRESET)}


@router.post("/tonesets/{item_id}/test", dependencies=[Depends(write_auth)])
async def test_toneset(request: Request, item_id: str) -> dict[str, bool]:
    if not any(value.id == item_id for value in request.app.state.config.tone_sets):
        raise HTTPException(404, "not found")
    call_id = UUID(int=__import__("secrets").randbits(128))
    now = __import__("datetime").datetime.now().astimezone()
    request.app.state.bus.publish(ToneDetected(call_id, item_id, now, "test", True))
    request.app.state.bus.publish(CallClosed(call_id, "tested", "test", True))
    from tonewatch.api.audit import record_audit

    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="test_trigger",
        resource=item_id,
        details={"call_id": str(call_id)},
    )
    return {"ok": True}
