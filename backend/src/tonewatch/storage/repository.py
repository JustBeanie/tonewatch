"""Typed repository boundary; ORM objects do not escape this module."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import Call, CallToneSet


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


async def create_call_tone_set(
    session: AsyncSession,
    *,
    call_id: UUID,
    toneset_id: str,
    detected_at: datetime,
    matched_segment_freqs: list[float] | None = None,
) -> None:
    """Insert a matched tone set once for a call."""
    tone_set = CallToneSet(
        call_id=call_id,
        toneset_id=toneset_id,
        detected_at=detected_at,
        matched_segment_freqs=matched_segment_freqs or [],
    )
    session.add(tone_set)
    await session.flush()


async def close_call(session: AsyncSession, *, call_id: UUID, status: str) -> None:
    """Set a call's terminal status."""
    call = await session.get(Call, call_id)
    if call is not None:
        call.status = status
        await session.flush()
