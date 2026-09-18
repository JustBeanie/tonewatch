"""SQLAlchemy ORM metadata for ToneWatch storage."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base."""


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    drill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    drill_keep: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    tone_sets: Mapped[list["CallToneSet"]] = relationship(cascade="all, delete-orphan")
    recordings: Mapped[list["Recording"]] = relationship(cascade="all, delete-orphan")
    alerts: Mapped[list["AlertAttempt"]] = relationship(cascade="all, delete-orphan")
    cad_incidents: Mapped[list["CallCadIncident"]] = relationship(cascade="all, delete-orphan")


class CallToneSet(Base):
    __tablename__ = "call_tone_sets"
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    toneset_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched_segment_freqs: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    agency_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agency_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now().astimezone()
    )


class AlertAttempt(Base):
    __tablename__ = "alert_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class CadIncident(Base):
    __tablename__ = "cad_incidents"
    __table_args__ = (UniqueConstraint("feed_id", "incident_id", name="uq_cad_incident_feed_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feed_id: Mapped[str] = mapped_column(String(100), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agency_name: Mapped[str] = mapped_column(String(300), nullable=False)
    agency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    agency_category: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    type_raw: Mapped[str] = mapped_column(String(300), nullable=False)
    type_key: Mapped[str] = mapped_column(String(300), nullable=False)
    type_code: Mapped[str | None] = mapped_column(String(300))
    address_clean: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cross_streets: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    municipality_raw: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    municipality_name: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(300), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallCadIncident(Base):
    __tablename__ = "call_cad_incidents"
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    feed_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delta_s: Mapped[float] = mapped_column(Float, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class DiscoveredTone(Base):
    """Persisted summary of an unmatched tone sequence."""

    __tablename__ = "discovered_tones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mean_frequencies: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    median_durations: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    duration_samples: Mapped[list[list[float]]] = mapped_column(JSON, nullable=False, default=list)
    frequency_minimums: Mapped[list[float]] = mapped_column(JSON, nullable=False, default=list)
    frequency_maximums: Mapped[list[float]] = mapped_column(JSON, nullable=False, default=list)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    observed_frequency_spread_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="new")
    best_clip_recording_path: Mapped[str | None] = mapped_column(Text)
    best_mean_purity: Mapped[float] = mapped_column(Float, nullable=False, default=0)


def create_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    """Create an async engine and session factory."""
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_wal(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine, async_sessionmaker(engine, expire_on_commit=False)
