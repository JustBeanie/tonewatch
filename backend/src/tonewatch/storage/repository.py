"""Typed repository boundary; ORM objects do not escape this module."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import Call


@dataclass(frozen=True)
class CallRecord:
    id: UUID
    started_at: datetime
    source_id: str
    status: str


async def create_call(session: AsyncSession, *, source_id: str, started_at: datetime) -> CallRecord:
    """Create a call and return a value object."""
    call = Call(source_id=source_id, started_at=started_at)
    session.add(call)
    await session.flush()
    return CallRecord(call.id, call.started_at, call.source_id, call.status)
