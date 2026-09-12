"""Non-blocking event-bus subscriber for call persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import av
import structlog
from sqlalchemy import select

from tonewatch.events import (
    CallClosed,
    EventBus,
    RecordingReady,
    RecordingStored,
    Subscription,
    ToneDetected,
)
from tonewatch.recording.retention import safe_recording_path
from tonewatch.storage.models import Call, CallToneSet, Recording
from tonewatch.storage.repository import close_call, create_call, create_call_tone_set

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

LOGGER = structlog.get_logger("tonewatch.persistence")


class PersistenceSubscriber:
    """Persist call events on a dedicated bounded-queue consumer task."""

    def __init__(
        self,
        bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession] | Callable[[], Any] | None,
        *,
        max_queue_size: int = 1000,
    ) -> None:
        """Create a bounded persistence subscriber."""
        self.bus, self.session_factory = bus, session_factory
        self._subscription: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._commit_task: asyncio.Task[None] | None = None
        self._busy = False
        self._max_queue_size = max_queue_size

    async def start(self) -> None:
        """Subscribe and start the consumer."""
        if self.session_factory is None or self._task is not None:
            return
        self._subscription = self.bus.subscribe(maxsize=self._max_queue_size)
        self._task = asyncio.create_task(self._consume(), name="tonewatch-persistence")

    async def stop(self, *, timeout_s: float | None = None) -> None:
        """Drain or cancel the consumer, keeping shutdown task ownership explicit."""
        if self._subscription is not None:
            self.bus.unsubscribe(self._subscription)
            self._subscription = None
        task = self._task
        if task is None:
            return
        try:
            if timeout_s is None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                await asyncio.wait_for(asyncio.shield(task), max(0.0, timeout_s))
        except TimeoutError:
            await self._abandon_commit()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            await self._abandon_commit()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            self._task = None

    async def _abandon_commit(self) -> None:
        commit_task = self._commit_task
        if commit_task is None or commit_task.done():
            return
        LOGGER.warning("persistence commit abandoned at shutdown")
        commit_task.cancel()
        await asyncio.gather(commit_task, return_exceptions=True)
        self._commit_task = None

    async def drain(self) -> None:
        """Wait until the currently queued events have been committed."""
        if self._subscription is None:
            return
        await asyncio.sleep(0)
        await self._subscription.queue.join()
        await asyncio.sleep(0)

    async def _consume(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return
        async for event in subscription:
            self._busy = True
            try:
                await self._persist(event)
            finally:
                self._busy = False
                subscription.queue.task_done()

    async def _persist(self, event: object) -> None:
        if not isinstance(event, (ToneDetected, CallClosed, RecordingReady)):
            return
        if self.session_factory is None:
            return
        async with self.session_factory() as session:
            if isinstance(event, ToneDetected):
                await self._persist_detection(session, event)
            elif isinstance(event, RecordingReady):
                stored = await self._persist_recording(session, event)
            else:
                await close_call(session, call_id=event.call_id, status=event.status)
            commit_task = asyncio.create_task(session.commit(), name="tonewatch-persistence-commit")
            self._commit_task = commit_task
            try:
                await asyncio.shield(commit_task)
            except asyncio.CancelledError:
                commit_task.cancel()
                await asyncio.gather(commit_task, return_exceptions=True)
                raise
            finally:
                if self._commit_task is commit_task:
                    self._commit_task = None
        if isinstance(event, RecordingReady):
            self.bus.publish(stored)

    async def reconcile_orphans(self, recordings_root: Path) -> None:
        """Restore valid encoded files that have no database row."""
        if self.session_factory is None:
            return
        root = recordings_root.resolve()
        files = await asyncio.to_thread(_recording_files, root)
        if not files:
            return
        async with self.session_factory() as session:
            result = await session.execute(select(Recording))
            rows = list(result.scalars().all())
            result.close()
            known = {Path(row.path).resolve() for row in rows}
            changed = False
            unrecognized: list[str] = []
            for path in files:
                if path in known:
                    continue
                try:
                    call_id = UUID(path.stem)
                except ValueError:
                    unrecognized.append(_relative_path(root, path))
                    continue
                try:
                    safe_recording_path(root, path)
                except ValueError:
                    LOGGER.warning(
                        "skipping recording file",
                        path=_relative_path(root, path),
                        reason="unsafe_path",
                    )
                    continue
                try:
                    duration, size_bytes = await asyncio.to_thread(
                        _recording_facts, path, require_metadata=True
                    )
                except (OSError, av.error.FFmpegError):
                    LOGGER.warning(
                        "skipping recording file",
                        path=_relative_path(root, path),
                        reason="metadata_unavailable",
                    )
                    continue
                call = await session.get(Call, call_id)
                if call is None:
                    stat = await asyncio.to_thread(path.stat)
                    session.add(
                        Call(
                            id=call_id,
                            source_id="",
                            started_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                            status="interrupted",
                        )
                    )
                elif call.status not in {"recorded", "failed", "interrupted"}:
                    call.status = "interrupted"
                session.add(
                    Recording(
                        call_id=call_id,
                        format="mp3" if path.suffix.lower() == ".mp3" else "opus",
                        path=str(path),
                        duration_s=duration,
                        size_bytes=size_bytes,
                    )
                )
                changed = True
            if unrecognized:
                LOGGER.info(
                    "skipping unrecognized recording files",
                    count=len(unrecognized),
                    paths=unrecognized,
                )
            if changed:
                commit_task = asyncio.create_task(
                    session.commit(), name="tonewatch-reconcile-commit"
                )
                await asyncio.shield(commit_task)
            await session.close()

    async def _persist_recording(
        self, session: AsyncSession, event: RecordingReady
    ) -> RecordingStored:
        """Persist file facts measured from the encoded file."""
        path = Path(event.path)
        duration, size_bytes = await asyncio.to_thread(_recording_facts, path)
        session.add(
            recording := Recording(
                call_id=event.call_id,
                format=event.format,
                path=str(path),
                duration_s=duration,
                size_bytes=size_bytes,
            )
        )
        await session.flush()
        return RecordingStored(
            call_id=event.call_id,
            recording_id=recording.id,
            format=event.format,
            source_id=event.source_id,
            test=event.test,
        )

    async def _persist_detection(self, session: AsyncSession, event: ToneDetected) -> None:
        # Calls arrive before their first tone-set row, and the subscriber is serial.
        if await session.get(Call, event.call_id) is None:
            await create_call(
                session,
                call_id=event.call_id,
                source_id=event.source_id,
                started_at=event.detected_at,
            )
        if await session.get(CallToneSet, (event.call_id, event.toneset_id)) is None:
            await create_call_tone_set(
                session,
                call_id=event.call_id,
                toneset_id=event.toneset_id,
                detected_at=event.detected_at,
            )


def _recording_facts(path: Path, *, require_metadata: bool = False) -> tuple[float, int]:
    """Read encoded-file metadata in a worker thread."""
    duration = 0.0
    try:
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is not None and stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
    except (OSError, av.error.FFmpegError):
        if require_metadata:
            raise
        duration = 0.0
    return duration, path.stat().st_size


def _recording_files(root: Path) -> list[Path]:
    """Find supported audio files without following symlinked files."""
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp3", ".ogg"}
    ]


def _relative_path(root: Path, path: Path) -> str:
    """Return a log-safe path relative to the recordings root."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
