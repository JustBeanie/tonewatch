"""Typed domain events and a non-blocking async event bus."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ToneDetected:
    call_id: UUID
    toneset_id: str
    detected_at: datetime
    source_id: str = ""
    test: bool = False


@dataclass(frozen=True)
class RecordingReady:
    call_id: UUID
    path: str
    format: str


@dataclass(frozen=True)
class FeedHealthChanged:
    source_id: str
    healthy: bool
    reason: str = ""


@dataclass(frozen=True)
class CallClosed:
    call_id: UUID
    status: str
    source_id: str = ""
    test: bool = False


@dataclass(frozen=True)
class ConfigChanged:
    revision: int


Event = ToneDetected | RecordingReady | FeedHealthChanged | CallClosed | ConfigChanged


class Subscription(AsyncIterator[Event]):
    """A bounded subscription with observable drop count."""

    def __init__(self, event_type: type[Event] | None, maxsize: int) -> None:
        self.event_type = event_type
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0
        self.closed = False

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> Event:
        if self.closed and self.queue.empty():
            raise StopAsyncIteration
        return await self.queue.get()

    def close(self) -> None:
        self.closed = True


class EventBus:
    """Fan-out bus whose publishing operation never waits on subscribers."""

    def __init__(self, *, max_queue_size: int = 1000) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[Subscription] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(
        self, event_type: type[Event] | None = None, *, maxsize: int | None = None
    ) -> Subscription:
        """Subscribe to one event type, or all events."""
        with suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()
        subscription = Subscription(event_type, maxsize or self._max_queue_size)
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        """Remove and close a subscription."""
        self._subscribers.discard(subscription)
        subscription.close()

    def publish(self, event: Event) -> None:
        """Schedule delivery safely from an audio callback thread."""
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is None:
            raise RuntimeError("EventBus.publish requires an active event loop")
        self._loop = loop
        loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: Event) -> None:
        for subscription in tuple(self._subscribers):
            if subscription.closed or (
                subscription.event_type is not None
                and not isinstance(event, subscription.event_type)
            ):
                continue
            if subscription.queue.full():
                subscription.queue.get_nowait()
                subscription.dropped += 1
            subscription.queue.put_nowait(event)
