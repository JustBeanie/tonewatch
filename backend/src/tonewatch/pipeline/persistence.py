"""Non-blocking event-bus subscriber for call persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import av

from tonewatch.events import (
    CallClosed,
    EventBus,
    RecordingReady,
    RecordingStored,
    Subscription,
    ToneDetected,
)
from tonewatch.storage.models import Call, CallToneSet, Recording
from tonewatch.storage.repository import close_call, create_call, create_call_tone_set

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
        self._busy = False
        self._max_queue_size = max_queue_size

    async def start(self) -> None:
        """Subscribe and start the consumer."""
        if self.session_factory is None or self._task is not None:
            return
        self._subscription = self.bus.subscribe(maxsize=self._max_queue_size)
        self._task = asyncio.create_task(self._consume(), name="tonewatch-persistence")

    async def stop(self) -> None:
        """Cancel the consumer and close its subscription."""
        if self._subscription is not None:
            self.bus.unsubscribe(self._subscription)
            self._subscription = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

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
            await session.commit()
        if isinstance(event, RecordingReady):
            self.bus.publish(stored)

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


def _recording_facts(path: Path) -> tuple[float, int]:
    """Read encoded-file metadata in a worker thread."""
    duration = 0.0
    try:
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is not None and stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
    except (OSError, av.error.FFmpegError):
        duration = 0.0
    return duration, path.stat().st_size
