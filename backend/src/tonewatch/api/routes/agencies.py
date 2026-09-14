"""Authenticated agency CRUD and GeoJSON export."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import _dump, authenticated, save_config, write_auth
from tonewatch.config.models import Agency, AppConfig
from tonewatch.config.store import replace_config

router = APIRouter(prefix="/api", tags=["agencies"])


def _agency_config(request: Request, agencies: list[Agency]) -> AppConfig:
    return replace_config(request.app.state.config, agencies=agencies)


async def _save_agency(
    request: Request, item: Agency, event_type: str, before: Agency | None
) -> Agency:
    try:
        current = request.app.state.config
        agencies = [value for value in current.agencies if value.id != item.id] + [item]
        await save_config(request, _agency_config(request, agencies), audit=False)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type=event_type,
        resource=item.id,
        before=_dump(before) if before else None,
        after=_dump(item),
    )
    return item


@router.get("/agencies", dependencies=[Depends(authenticated)])
async def list_agencies(request: Request) -> list[Any]:
    return [_dump(value) for value in request.app.state.config.agencies]


@router.post("/agencies", dependencies=[Depends(write_auth)], status_code=201)
async def create_agency(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
    try:
        item = Agency.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    if any(value.id == item.id for value in request.app.state.config.agencies):
        raise HTTPException(409, "agency id already exists")
    return _dump(await _save_agency(request, item, "agency_created", None))


@router.get("/agencies/{item_id}", dependencies=[Depends(authenticated)])
async def get_agency(request: Request, item_id: str) -> Any:
    item = next((value for value in request.app.state.config.agencies if value.id == item_id), None)
    if item is None:
        raise HTTPException(404, "not found")
    return _dump(item)


@router.put("/agencies/{item_id}", dependencies=[Depends(write_auth)])
async def update_agency(request: Request, item_id: str, payload: dict[str, Any] = Body(...)) -> Any:
    if payload.get("id") != item_id:
        raise HTTPException(422, "id does not match path")
    try:
        item = Agency.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    before = next(
        (value for value in request.app.state.config.agencies if value.id == item_id), None
    )
    if before is None:
        raise HTTPException(404, "not found")
    return _dump(await _save_agency(request, item, "agency_updated", before))


@router.delete("/agencies/{item_id}", dependencies=[Depends(write_auth)])
async def delete_agency(request: Request, item_id: str) -> Any:
    current = request.app.state.config
    item = next((value for value in current.agencies if value.id == item_id), None)
    if item is None:
        raise HTTPException(404, "not found")
    refs = [tone.id for tone in current.tone_sets if tone.agency_id == item_id]
    if refs:
        raise HTTPException(409, f"agency {item_id} is referenced by tone sets: {', '.join(refs)}")
    await save_config(
        request,
        _agency_config(request, [value for value in current.agencies if value.id != item_id]),
        audit=False,
    )
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="agency_deleted",
        resource=item_id,
        before=_dump(item),
    )
    return {"ok": True}


@router.get("/agencies.geojson", dependencies=[Depends(authenticated)])
async def agencies_geojson(request: Request) -> JSONResponse:
    features: list[dict[str, Any]] = []
    for agency in request.app.state.config.agencies:
        properties = {
            "id": agency.id,
            "name": agency.name,
            "short_name": agency.short_name,
            "kind": agency.kind,
            "color": agency.color,
            "cad_names": agency.cad_names,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [agency.location.lon, agency.location.lat],
                },
                "properties": properties,
            }
        )
        features.extend(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [station.lon, station.lat]},
                "properties": {**properties, "station_of": agency.id, "name": station.name},
            }
            for station in agency.stations
        )
        if agency.coverage is not None:
            features.append(
                {"type": "Feature", "geometry": agency.coverage, "properties": properties}
            )
    return JSONResponse(
        {"type": "FeatureCollection", "features": features}, media_type="application/geo+json"
    )
