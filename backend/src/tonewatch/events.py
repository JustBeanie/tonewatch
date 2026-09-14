"""Typed domain events and a non-blocking async event bus."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tonewatch.dsp.discovery import ToneCandidate


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
    source_id: str = ""
    test: bool = False


@dataclass(frozen=True)
class RecordingStored:
    """Identify a recording after its database row is committed."""

    call_id: UUID
    recording_id: int
    format: str
    source_id: str = ""
    test: bool = False


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


@dataclass(frozen=True)
class ChannelLevel:
    """A throttled instantaneous level sample for one source."""

    source_id: str
    rms_dbfs: float
    peak: float
    measured_at: datetime


@dataclass(frozen=True)
class SpectrumUpdate:
    """A live spectrum update intended for subscribed clients."""

    source_id: str
    dominant_frequency_hz: float
    purity: float
    level_dbfs: float
    magnitude: tuple[float, ...]
    measured_at: datetime


@dataclass(frozen=True)
class ToneCandidateObserved:
    """An unmatched candidate observed by one channel."""

    candidate: ToneCandidate
    source_id: str
    observed_at: datetime
    clip_samples: bytes | None = None


@dataclass(frozen=True)
class ToneDiscovered:
    """A newly created persisted discovery cluster."""

    candidate: ToneCandidate
    source_id: str
    observed_at: datetime
    cluster_id: int | None = None
    count: int = 1
    clip_path: str | None = None


@dataclass(frozen=True)
class LiveListenersChanged:
    source_id: str
    source_listeners: int
    total_listeners: int


Event = (
    ToneDetected
    | RecordingReady
    | RecordingStored
    | FeedHealthChanged
    | CallClosed
    | ConfigChanged
    | ChannelLevel
    | SpectrumUpdate
    | ToneDiscovered
    | ToneCandidateObserved
    | LiveListenersChanged
)


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
        self._spectrum_topics: dict[str, int] = {}

    def set_spectrum_subscribers(self, source_id: str, count: int) -> None:
        """Set the number of clients interested in a source's live spectrum."""
        if count <= 0:
            self._spectrum_topics.pop(source_id, None)
        else:
            self._spectrum_topics[source_id] = count

    def spectrum_subscribed(self, source_id: str) -> bool:
        """Whether live spectrum work is currently requested for a source."""
        return self._spectrum_topics.get(source_id, 0) > 0

    def spectrum_subscriber_count(self, source_id: str) -> int:
        """Return the current live spectrum subscriber count."""
        return self._spectrum_topics.get(source_id, 0)

    @property
    def subscriber_count(self) -> int:
        """Number of active bus subscriptions."""
        return len(self._subscribers)

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
