"""CAD unmatched agency helpers."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select

from tonewatch.api.audit import record_audit
from tonewatch.api.deps import authenticated, save_config, write_auth
from tonewatch.config.models import Agency, AgencyLocation
from tonewatch.storage.models import CadIncident, CallCadIncident

router = APIRouter(prefix="/cad", tags=["cad"])


@router.get("/incidents", dependencies=[Depends(authenticated)])
async def incidents(
    request: Request,
    status: Literal["active", "closed"] = "active",
    configured_only: bool = True,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Return the small, authenticated incident projection used by the web UI."""
    configured = {
        name.casefold() for agency in request.app.state.config.agencies for name in agency.cad_names
    }
    async with request.app.state.session_factory() as session:
        query = select(CadIncident).where(CadIncident.status == status)
        if configured_only:
            if not configured:
                return []
            query = query.where(CadIncident.agency_key.in_(configured))
        rows = list(
            (
                await session.scalars(query.order_by(CadIncident.received_at.desc()).limit(limit))
            ).all()
        )
        link_filter = or_(
            *[
                and_(
                    CallCadIncident.feed_id == row.feed_id,
                    CallCadIncident.incident_id == row.incident_id,
                )
                for row in rows
            ]
        )
        links = (
            list((await session.scalars(select(CallCadIncident).where(link_filter))).all())
            if rows
            else []
        )
    call_by_incident = {(link.feed_id, link.incident_id): str(link.call_id) for link in links}
    return [
        {
            "feed_id": row.feed_id,
            "incident_id": row.incident_id,
            "agency_name": row.agency_name,
            "agency_key": row.agency_key,
            "type": {"raw": row.type_raw, "code": row.type_code},
            "address_clean": row.address_clean,
            "cross_streets": row.cross_streets,
            "municipality": row.municipality_name or row.municipality_raw,
            "received_at": row.received_at.isoformat(),
            "status": row.status,
            "call_id": call_by_incident.get((row.feed_id, row.incident_id)),
        }
        for row in rows
    ]


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
