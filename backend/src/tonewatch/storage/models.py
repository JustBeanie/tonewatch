"""SQLAlchemy ORM metadata for ToneWatch storage."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, event
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
    tone_sets: Mapped[list["CallToneSet"]] = relationship(cascade="all, delete-orphan")
    recordings: Mapped[list["Recording"]] = relationship(cascade="all, delete-orphan")
    alerts: Mapped[list["AlertAttempt"]] = relationship(cascade="all, delete-orphan")


class CallToneSet(Base):
    __tablename__ = "call_tone_sets"
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    toneset_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched_segment_freqs: Mapped[list[float]] = mapped_column(JSON, nullable=False)


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


def create_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    """Create an async engine and session factory."""
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_wal(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine, async_sessionmaker(engine, expire_on_commit=False)
