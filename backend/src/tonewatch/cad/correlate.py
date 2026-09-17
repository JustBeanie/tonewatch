"""Pure, deterministic CAD-to-call matching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from tonewatch.events import CallEnriched, EventBus, Subscription, ToneDetected
from tonewatch.storage.models import CadIncident, Call, CallCadIncident, CallToneSet

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Any

    from tonewatch.config.models import AppConfig


@dataclass(frozen=True)
class CorrelationIncident:
    """Minimal incident identity used by the pure matcher."""

    id: str
    agency_key: str
    received_at: datetime


@dataclass(frozen=True)
class CorrelationCall:
    """Minimal call identity used by the pure matcher."""

    id: str
    started_at: datetime
    agency_cad_names: tuple[str, ...]


def choose_incident(
    call: CorrelationCall,
    incidents: Iterable[CorrelationIncident],
    *,
    before_s: float = 180,
    after_s: float = 300,
) -> CorrelationIncident | None:
    """Choose the closest agency-compatible incident in the configured window."""
    names = {name.casefold().strip() for name in call.agency_cad_names}
    lo = call.started_at - timedelta(seconds=before_s)
    hi = call.started_at + timedelta(seconds=after_s)
    choices = [
        i for i in incidents if i.agency_key.casefold() in names and lo <= i.received_at <= hi
    ]
    return min(
        choices,
        key=lambda i: (abs((i.received_at - call.started_at).total_seconds()), i.received_at),
        default=None,
    )


class CadCorrelationService:
    """Correlate persisted CAD incidents with persisted calls."""

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        session_factory: Callable[[], Any],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Build a correlation service with injected persistence and clock dependencies."""
        self.config, self.bus, self.session_factory, self.clock = (
            config,
            bus,
            session_factory,
            clock,
        )
        self.subscription: Subscription | None = None
        self.task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start listening for call-start events."""
        if self.task is not None:
            return
        self.subscription = self.bus.subscribe(ToneDetected)
        self.task = asyncio.create_task(self._consume(), name="tonewatch-cad-correlation")

    async def stop(self) -> None:
        """Stop the correlation consumer cleanly."""
        if self.subscription is not None:
            self.bus.unsubscribe(self.subscription)
            self.subscription = None
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def reload(self, config: AppConfig) -> None:
        """Apply the current agency and feed windows."""
        self.config = config

    async def _consume(self) -> None:
        if self.subscription is None:
            return
        async for event in self.subscription:
            if isinstance(event, ToneDetected):
                await self.on_call_start(event)

    async def on_call_start(self, event: ToneDetected) -> None:
        """Match a newly started call against every configured feed."""
        names = self._names_for_event(event)
        async with self._lock:
            for _attempt in range(5):
                async with self.session_factory() as session:
                    call = await session.get(Call, event.call_id)
                if call is not None:
                    break
                await asyncio.sleep(0)
            if call is None:
                return
            await self._correlate_call(call, names)

    def _names_for_event(self, event: ToneDetected) -> tuple[str, ...]:
        agency_id = event.agency.get("id") if event.agency else None
        agency = next((item for item in self.config.agencies if item.id == agency_id), None)
        return tuple(agency.cad_names) if agency is not None else ()

    async def on_incident(self, feed_id: str, incident_id: str) -> None:
        """Match a newly persisted incident to eligible nearby calls."""
        async with self._lock:
            async with self.session_factory() as session:
                incident = await session.scalar(
                    select(CadIncident).where(
                        CadIncident.feed_id == feed_id,
                        CadIncident.incident_id == incident_id,
                    )
                )
                if incident is None:
                    return
                calls = list((await session.scalars(select(Call))).all())
            for call in calls:
                await self._correlate_call(call, None, feed_id=feed_id)

    async def _correlate_call(
        self,
        call: Call,
        event_names: tuple[str, ...] | None,
        *,
        feed_id: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            tone_rows = list(
                (
                    await session.scalars(select(CallToneSet).where(CallToneSet.call_id == call.id))
                ).all()
            )
            names = event_names or self._names_for_tone_rows(tone_rows)
            feeds = [item for item in self.config.cad_feeds if item.enabled]
            if feed_id is not None:
                feeds = [item for item in feeds if item.id == feed_id]
            for feed in feeds:
                linked = await session.scalar(
                    select(CallCadIncident).where(
                        CallCadIncident.call_id == call.id,
                        CallCadIncident.feed_id == feed.id,
                    )
                )
                if linked is not None or not names:
                    continue
                lo = call.started_at - timedelta(seconds=feed.window_before_s)
                hi = call.started_at + timedelta(seconds=feed.window_after_s)
                rows = list(
                    (
                        await session.scalars(
                            select(CadIncident).where(
                                CadIncident.feed_id == feed.id,
                                CadIncident.received_at >= lo,
                                CadIncident.received_at <= hi,
                            )
                        )
                    ).all()
                )
                chosen = choose_incident(
                    CorrelationCall(str(call.id), call.started_at, names),
                    (
                        CorrelationIncident(row.incident_id, row.agency_key, row.received_at)
                        for row in rows
                    ),
                    before_s=feed.window_before_s,
                    after_s=feed.window_after_s,
                )
                if chosen is None:
                    continue
                row = next(item for item in rows if item.incident_id == chosen.id)
                matched_at = self.clock()
                session.add(
                    CallCadIncident(
                        call_id=call.id,
                        feed_id=feed.id,
                        incident_id=row.incident_id,
                        matched_at=matched_at,
                        delta_s=(row.received_at - call.started_at).total_seconds(),
                    )
                )
                await session.commit()
                self.bus.publish(
                    CallEnriched(
                        call_id=call.id,
                        feed_id=feed.id,
                        incident_id=row.incident_id,
                        incident=_incident_payload(row),
                        matched_at=matched_at,
                    )
                )

    def _names_for_tone_rows(self, rows: list[CallToneSet]) -> tuple[str, ...]:
        ids = {row.agency_id for row in rows if row.agency_id is not None}
        return tuple(
            name for agency in self.config.agencies if agency.id in ids for name in agency.cad_names
        )


def _incident_payload(row: CadIncident) -> dict[str, object]:
    """Return the bounded, address-bearing enrichment payload."""
    return {
        "feed_id": row.feed_id,
        "incident_id": row.incident_id,
        "agency": {
            "name": row.agency_name,
            "key": row.agency_key,
            "category": row.agency_category,
        },
        "type": {"raw": row.type_raw, "key": row.type_key, "code": row.type_code},
        "address_clean": row.address_clean,
        "cross_streets": row.cross_streets,
        "municipality": {"raw": row.municipality_raw, "name": row.municipality_name},
        "received_at": row.received_at.isoformat(),
    }
