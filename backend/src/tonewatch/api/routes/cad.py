"""CAD unmatched agency helpers."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import authenticated, save_config, write_auth
from tonewatch.config.models import Agency, AgencyLocation
from tonewatch.storage.models import CadIncident

router = APIRouter(prefix="/cad", tags=["cad"])


@router.get("/unmatched-agencies", dependencies=[Depends(authenticated)])
async def unmatched(request: Request) -> list[dict[str, Any]]:
    configured = {
        name.casefold() for agency in request.app.state.config.agencies for name in agency.cad_names
    }
    async with request.app.state.session_factory() as session:
        rows = (
            await session.execute(
                select(
                    CadIncident.agency_key,
                    CadIncident.agency_name,
                    func.count(CadIncident.id),
                    func.max(CadIncident.last_seen_at),
                ).group_by(CadIncident.agency_key, CadIncident.agency_name)
            )
        ).all()
    return [
        {"key": key, "name": name, "count": count, "last_seen": last.isoformat() if last else None}
        for key, name, count, last in rows
        if key.casefold() not in configured
    ]


@router.post(
    "/unmatched-agencies/{key}/create-agency", dependencies=[Depends(write_auth)], status_code=201
)
async def create_agency(request: Request, key: str) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        row = (
            (
                await session.execute(
                    select(CadIncident)
                    .where(CadIncident.agency_key == key)
                    .order_by(CadIncident.last_seen_at.desc())
                )
            )
            .scalars()
            .first()
        )
    if row is None:
        raise HTTPException(404, "unmatched agency not found")
    agency_id = key.casefold().replace(" ", "-")
    agency = Agency(
        id=agency_id,
        name=row.agency_name,
        short_name=row.agency_name[:80],
        kind=row.agency_category
        if row.agency_category in {"fire", "ems", "police", "rescue", "dispatch", "other"}
        else "other",
        color="#666666",
        location=AgencyLocation(lat=0, lon=0),
        cad_names=[row.agency_name],
    )
    config = request.app.state.config
    if any(item.id == agency.id for item in config.agencies):
        raise HTTPException(409, "agency already exists")
    await save_config(request, config.model_copy(update={"agencies": [*config.agencies, agency]}))
    await record_audit(
        request.app.state.session_factory,
        actor=getattr(request.state, "auth", "unknown"),
        event_type="cad_agency_created",
        resource=agency.id,
        details={"cad_key": key},
    )
    return agency.model_dump(mode="json")
