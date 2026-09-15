"""Configuration resource route registration boundary."""

import asyncio
from collections import Counter
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from tonewatch.api.deps import _dump, authenticated, collection, put, save_config, write_auth
from tonewatch.config.models import AlertTarget, AppConfig, Source, ToneSet
from tonewatch.config.store import replace_config as rebuild_config
from tonewatch.dsp.squelch import Squelch, SquelchConfig
from tonewatch.events import CallClosed, ToneDetected
from tonewatch.storage.models import DiscoveredTone

router = APIRouter(prefix="/api", tags=["configuration"])
_SQUELCH_DIAGNOSTIC_KEYS = (
    "squelch_mode_effective",
    "noise_floor_dbfs",
    "open_dbfs_effective",
    "close_dbfs_effective",
    "calibrating",
    "stuck_open",
    "chatter",
    "transitions_per_min",
)


def _empty_squelch_diagnostics() -> dict[str, None]:
    return dict.fromkeys(_SQUELCH_DIAGNOSTIC_KEYS)


def _source_diagnostics(supervisor: Any, source_id: str) -> dict[str, object] | None:
    getter = getattr(supervisor, "source_diagnostics", None)
    return getter(source_id) if callable(getter) else None


class CalibrateRequest(BaseModel):
    seconds: float = Field(ge=5, le=120)


@router.post("/sources/{source_id}/squelch/calibrate", dependencies=[Depends(write_auth)])
async def calibrate_squelch(request: Request, source_id: str, payload: CalibrateRequest) -> Any:
    """Estimate thresholds from the already-running channel's level tap."""
    source = next((item for item in request.app.state.config.sources if item.id == source_id), None)
    if source is None:
        raise HTTPException(404, "source not found")
    supervisor = getattr(request.app.state, "supervisor", None)
    channel = supervisor.channel_for(source_id) if supervisor is not None else None
    if channel is None:
        raise HTTPException(409, "source is not running")
    active: set[str] = getattr(request.app.state, "squelch_calibrations", set())
    request.app.state.squelch_calibrations = active
    if source_id in active:
        raise HTTPException(429, "calibration already running")
    active.add(source_id)
    levels: list[float] = []

    def tap(level: float) -> None:
        levels.append(level)

    channel.add_level_tap(tap)
    try:
        await asyncio.sleep(payload.seconds)
    finally:
        channel.remove_level_tap(tap)
        active.discard(source_id)
    estimator = Squelch(SquelchConfig(mode="auto", auto_window_s=300))
    for index, level in enumerate(levels):
        estimator.feed(level, index * 0.2)
    p10, p50, p90 = estimator.percentiles()
    if p10 is None or p50 is None or p90 is None:
        raise HTTPException(409, "source produced no levels")
    spread = p50 - p10
    open_dbfs = p10 + max(6.0, min(25.0, 1.5 * spread))
    close_dbfs = open_dbfs - max(3.0, spread / 2)
    buckets = Counter(round(level / 3) * 3 for level in levels)
    result = {
        "floor_dbfs": p10,
        "spread_db": spread,
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "histogram": [
            {"dbfs": bucket, "count": count} for bucket, count in sorted(buckets.items())
        ],
        "suggested": {"mode": "level", "open_dbfs": open_dbfs, "close_dbfs": close_dbfs},
    }
    from tonewatch.api.audit import record_audit

    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="squelch_calibrated",
        resource=source_id,
        details={
            "source_id": source_id,
            "seconds": payload.seconds,
            "suggested": result["suggested"],
        },
    )
    return result


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
                item.update(
                    (_source_diagnostics(supervisor, value.id) if supervisor is not None else None)
                    or _empty_squelch_diagnostics()
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
            result.update(
                (_source_diagnostics(supervisor, item.id) if supervisor is not None else None)
                or _empty_squelch_diagnostics()
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


@router.post("/alert-targets/{item_id}/test", dependencies=[Depends(write_auth)])
async def test_alert_target(request: Request, item_id: str) -> dict[str, object]:
    """Send one synthetic TEST message through the selected alert target."""
    if not any(value.id == item_id for value in request.app.state.config.alert_targets):
        raise HTTPException(404, "not found")
    try:
        result = await request.app.state.supervisor.alerts.test_target(item_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    from tonewatch.api.audit import record_audit

    await record_audit(
        getattr(request.app.state, "session_factory", None),
        actor=getattr(getattr(request, "state", None), "auth", "unknown"),
        event_type="alert_target_test",
        resource=item_id,
        details={"ok": bool(result.get("ok"))},
    )
    return result


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
