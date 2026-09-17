"""Safe parsing and state handling for untrusted icad2mqtt messages."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from tonewatch.storage.models import CadIncident as CadIncidentRow

MAX_PAYLOAD_BYTES = 1024 * 1024
_ID = re.compile(r"^[0-9a-f]{8,64}$")
CadText = Annotated[str, Field(max_length=300)]


class CadAgency(BaseModel):
    """Validated CAD agency identity."""

    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=300)
    key: str = Field(min_length=1, max_length=300)
    category: str = Field(default="", max_length=300)
    category_source: str = Field(default="", max_length=300)


class CadType(BaseModel):
    """Validated CAD incident type."""

    model_config = ConfigDict(extra="ignore")
    raw: str = Field(min_length=1, max_length=300)
    key: str = Field(min_length=1, max_length=300)
    code: str | None = Field(default=None, max_length=300)


class CadMunicipality(BaseModel):
    """Validated municipality fields."""

    model_config = ConfigDict(extra="ignore")
    raw: str = Field(default="", max_length=300)
    name: str | None = Field(default=None, max_length=300)


class CadIncident(BaseModel):
    """Validated incident payload with bounded strings."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_ID.pattern)
    agency: CadAgency
    received_at: datetime
    received_at_raw: str = Field(default="", max_length=300)
    type: CadType
    address_raw: str = Field(default="", max_length=300)
    address_clean: str = Field(default="", max_length=300)
    municipality: CadMunicipality = Field(default_factory=CadMunicipality)
    cross_streets_raw: str = Field(default="", max_length=300)
    cross_streets: list[CadText] = Field(default_factory=list, max_length=20)
    status: str = Field(default="active", min_length=1, max_length=300)

    @field_validator("received_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        """Reject timestamps without an explicit offset."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        return value


class CadSnapshot(BaseModel):
    """Authoritative retained incident snapshot."""

    model_config = ConfigDict(extra="ignore")
    schema_: Literal[1] = Field(alias="schema")
    source: str = Field(default="", max_length=300)
    page_updated_at: datetime | None = None
    fetched_at: datetime
    incidents: list[CadIncident] = Field(max_length=500)

    @field_validator("fetched_at", "page_updated_at")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        """Require offsets on snapshot timestamps when present."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError
        return value


class CadEvent(BaseModel):
    """Non-retained incident transition event."""

    model_config = ConfigDict(extra="ignore")
    schema_: Literal[1] = Field(alias="schema")
    event: Literal["new", "updated", "closed"]
    incident: CadIncident


def parse_message(
    payload: bytes | str, topic: str = "", *, logger: logging.Logger | None = None
) -> CadSnapshot | CadEvent | str:
    """Validate a message, returning a typed object or a safe rejection reason."""
    raw = payload.encode() if isinstance(payload, str) else payload
    if len(raw) > MAX_PAYLOAD_BYTES:
        return "payload exceeds 1 MiB"
    try:
        value: Any = json.loads(raw)
        if topic.endswith("/incidents"):
            return CadSnapshot.model_validate(value)
        if topic.endswith("/incident"):
            return CadEvent.model_validate(value)
        if topic.endswith("/availability"):
            return value if value in {"online", "offline"} else "invalid availability"
        else:  # noqa: RET505 -- keeps unsupported topics in the safe parser branch.
            return "unsupported topic"
    except Exception as exc:  # hostile input must never escape the feed task
        if logger:
            logger.warning(
                "invalid CAD message",
                extra={"feed_id": "", "topic": topic, "reason": type(exc).__name__},
            )
        return "invalid message"


class FeedHealth:
    """Mutable operational counters for one feed."""

    def __init__(self) -> None:
        """Initialize an empty health record."""
        self.connected = False
        self.availability: str | None = None
        self.last_message_at: datetime | None = None
        self.invalid_count = 0
        self.invalid_total = 0
        self.active_incidents = 0


class CadFeedRunner:
    """Small injectable lifecycle wrapper; broker implementations are supplied by callers."""

    def __init__(
        self,
        feed: Any,
        *,
        client_factory: Any,
        session_factory: Any = None,
        sleep: Any = asyncio.sleep,
        jitter: Any = lambda delay: delay,
    ) -> None:
        """Build an injectable broker runner."""
        self.feed, self.client_factory, self.sleep, self.jitter = (
            feed,
            client_factory,
            sleep,
            jitter,
        )
        self.session_factory = session_factory
        self.logger = logging.getLogger("tonewatch.cad")
        self.health = FeedHealth()
        self._stopping = False
        self.on_incident: Any = None

    async def run(self) -> None:
        """Consume messages and reconnect with bounded backoff."""
        delay = 1.0
        while not self._stopping:
            try:
                async with self.client_factory(self.feed) as client:
                    self.health.connected = True
                    await client.subscribe(f"{self.feed.base_topic}/incidents", qos=1)
                    await client.subscribe(f"{self.feed.base_topic}/incident", qos=1)
                    await client.subscribe(f"{self.feed.base_topic}/availability", qos=1)
                    delay = 1.0
                    async for message in client.messages:
                        self.health.last_message_at = datetime.now().astimezone()
                        parsed = parse_message(message.payload, str(message.topic))
                        if (
                            isinstance(parsed, str)
                            and parsed in {"online", "offline"}
                            and str(message.topic).endswith("/availability")
                        ):
                            self.health.availability = parsed
                        elif isinstance(parsed, str):
                            self.health.invalid_count += 1
                            self.health.invalid_total = self.health.invalid_count
                            self.logger.warning(
                                "invalid CAD message feed=%s topic=%s reason=%s count=%s",
                                self.feed.id,
                                str(message.topic),
                                parsed,
                                self.health.invalid_count,
                            )
                        elif self.session_factory is not None:
                            await self.persist(parsed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.health.connected = False
                self.logger.warning(
                    "CAD feed disconnected feed=%s reason=%s", self.feed.id, type(exc).__name__
                )
                await self.sleep(self.jitter(min(60.0, delay)))
                delay = min(60.0, delay * 2)

    def stop(self) -> None:
        """Request shutdown after the current client exits."""
        self._stopping = True

    async def persist(self, parsed: CadSnapshot | CadEvent) -> None:
        """Apply a validated snapshot or transition to the authoritative store."""
        now = datetime.now(UTC)
        correlation_ids: set[str] = set()
        async with self.session_factory() as session:
            if isinstance(parsed, CadSnapshot):
                incoming = {item.id: item for item in parsed.incidents}
                rows = list(
                    (
                        await session.scalars(
                            select(CadIncidentRow).where(CadIncidentRow.feed_id == self.feed.id)
                        )
                    ).all()
                )
                for row in rows:
                    if row.incident_id not in incoming and row.closed_at is None:
                        row.status = "closed"
                        row.closed_at = parsed.fetched_at.astimezone(UTC)
                for incident in parsed.incidents:
                    if await self._upsert(session, incident, now, parsed.fetched_at):
                        correlation_ids.add(incident.id)
            else:
                await self._upsert(
                    session, parsed.incident, now, now, closed=parsed.event == "closed"
                )
                if parsed.event in {"new", "updated"}:
                    correlation_ids.add(parsed.incident.id)
            await session.commit()
            self.health.active_incidents = len(
                (
                    await session.scalars(
                        select(CadIncidentRow).where(
                            CadIncidentRow.feed_id == self.feed.id,
                            CadIncidentRow.closed_at.is_(None),
                        )
                    )
                ).all()
            )
        if self.on_incident is not None:
            for incident_id in correlation_ids:
                try:
                    await self.on_incident(self.feed.id, incident_id)
                except Exception as exc:
                    self.logger.warning(
                        "CAD correlation failed feed=%s reason=%s",
                        self.feed.id,
                        type(exc).__name__,
                    )

    async def _upsert(
        self,
        session: Any,
        incident: CadIncident,
        now: datetime,
        seen_at: datetime,
        *,
        closed: bool = False,
    ) -> bool:
        """Insert or update one validated incident without logging its fields."""
        row = (
            await session.scalars(
                select(CadIncidentRow).where(
                    CadIncidentRow.feed_id == self.feed.id,
                    CadIncidentRow.incident_id == incident.id,
                )
            )
        ).first()
        received = incident.received_at.astimezone(UTC)
        if row is None:
            row = CadIncidentRow(
                feed_id=self.feed.id,
                incident_id=incident.id,
                agency_name=incident.agency.name,
                agency_key=incident.agency.key,
                agency_category=incident.agency.category,
                type_raw=incident.type.raw,
                type_key=incident.type.key,
                type_code=incident.type.code,
                address_clean=incident.address_clean,
                cross_streets=incident.cross_streets,
                municipality_raw=incident.municipality.raw,
                municipality_name=incident.municipality.name,
                received_at=received,
                status="closed" if closed else incident.status,
                first_seen_at=now,
                last_seen_at=seen_at.astimezone(UTC),
                closed_at=seen_at.astimezone(UTC) if closed else None,
            )
            session.add(row)
            return True
        row.last_seen_at = seen_at.astimezone(UTC)
        if closed:
            row.status = "closed"
            row.closed_at = seen_at.astimezone(UTC)
        else:
            row.status = incident.status
            row.closed_at = None if incident.status != "closed" else row.closed_at
        return False
