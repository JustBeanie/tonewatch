"""Typed repository boundary; ORM objects do not escape this module."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import Call, CallToneSet, DiscoveredTone


@dataclass(frozen=True)
class CallRecord:
    id: UUID
    started_at: datetime
    source_id: str
    status: str


async def create_call(
    session: AsyncSession,
    *,
    source_id: str,
    started_at: datetime,
    call_id: UUID | None = None,
) -> CallRecord:
    """Create a call and return a value object."""
    call = Call(id=call_id, source_id=source_id, started_at=started_at)
    session.add(call)
    await session.flush()
    return CallRecord(call.id, call.started_at, call.source_id, call.status)


async def create_call_tone_set(  # noqa: PLR0913 -- snapshot fields are the persistence contract.
    session: AsyncSession,
    *,
    call_id: UUID,
    toneset_id: str,
    detected_at: datetime,
    matched_segment_freqs: list[float] | None = None,
    agency_id: str | None = None,
    agency_name: str | None = None,
    agency_kind: str | None = None,
) -> None:
    """Insert a matched tone set once for a call."""
    tone_set = CallToneSet(
        call_id=call_id,
        toneset_id=toneset_id,
        detected_at=detected_at,
        matched_segment_freqs=matched_segment_freqs or [],
        agency_id=agency_id,
        agency_name=agency_name,
        agency_kind=agency_kind,
    )
    session.add(tone_set)
    await session.flush()


async def close_call(session: AsyncSession, *, call_id: UUID, status: str) -> None:
    """Set a call's terminal status."""
    call = await session.get(Call, call_id)
    if call is not None:
        call.status = status
        await session.flush()


async def list_discovered_tones(  # noqa: PLR0913 -- list filters are the repository query contract.
    session: AsyncSession,
    *,
    source_id: str | None = None,
    since: datetime | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DiscoveredTone]:
    """List discovered clusters using stable newest-first ordering."""
    query = select(DiscoveredTone).order_by(DiscoveredTone.last_seen.desc())
    if status:
        query = query.where(DiscoveredTone.status == status)
    if since:
        query = query.where(DiscoveredTone.last_seen >= since)
    result = await session.scalars(query)
    rows = list(result.all())
    result.close()
    if source_id:
        rows = [row for row in rows if source_id in row.source_ids]
    return rows[offset : offset + limit]


async def get_discovered_tone(session: AsyncSession, cluster_id: int) -> DiscoveredTone | None:
    """Return one discovered cluster."""
    return await session.get(DiscoveredTone, cluster_id)
