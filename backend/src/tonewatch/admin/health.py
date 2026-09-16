"""Pure, bounded runtime health metrics used by the admin API."""

from __future__ import annotations

import asyncio
import math
import re
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from tonewatch.events import EventBus, FeedHealthChanged

MAX_ERROR = 500
MAX_HISTORY = 50
MAX_FORECAST_DAYS = 3650.0
MIN_SAMPLES = 2
SCAN_INTERVAL_S = 60.0
URL_CREDENTIALS = re.compile(r"(://)[^/@\s]+@")


def bounded_error(value: object | None) -> str | None:
    """Return a short, non-secret diagnostic string."""
    if value is None:
        return None
    text = URL_CREDENTIALS.sub(r"\1[redacted]@", " ".join(str(value).split()))
    return text[:MAX_ERROR] if text else None


class RealtimeFactor:
    """EWMA of audio seconds processed per wall-clock DSP second."""

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, half_life_s: float = 30.0
    ) -> None:
        """Create an EWMA with an injectable monotonic clock."""
        self.clock = clock
        self.half_life_s = half_life_s
        self.value: float | None = None
        self._last_at: float | None = None

    def observe(
        self, audio_seconds: float, processing_seconds: float, now: float | None = None
    ) -> float | None:
        """Add one DSP observation and return the current factor."""
        if audio_seconds < 0 or processing_seconds <= 0:
            return self.value
        instant = audio_seconds / processing_seconds
        current = self.clock() if now is None else now
        if self.value is None:
            self.value = instant
        else:
            elapsed = max(0.0, current - (self._last_at if self._last_at is not None else current))
            alpha = 1.0 - math.exp(-math.log(2) * elapsed / self.half_life_s)
            self.value += alpha * (instant - self.value)
        self._last_at = current
        return self.value


@dataclass
class ChannelHealth:
    """Mutable bounded diagnostics for one source."""

    clock: Callable[[], float] = time.monotonic
    factor: RealtimeFactor = field(init=False)
    dropped_frames: int = 0
    late_frames: int = 0
    restarts: int = 0
    last_restart_at: datetime | None = None
    last_error: str | None = None
    level: dict[str, object] | None = None
    squelch_open: bool | None = None
    feed_health_history: deque[dict[str, object]] = field(init=False)

    def __post_init__(self) -> None:
        """Initialize bounded mutable fields."""
        self.factor = RealtimeFactor(self.clock)
        self.feed_health_history = deque(maxlen=MAX_HISTORY)

    def observe_frame(
        self, audio_seconds: float, processing_seconds: float, *, dropped: int = 0
    ) -> None:
        """Record DSP duration, late work, and source drops."""
        self.factor.observe(audio_seconds, processing_seconds)
        self.dropped_frames += max(0, dropped)
        if processing_seconds > audio_seconds:
            self.late_frames += 1

    def feed_changed(self, event: FeedHealthChanged, at: datetime) -> None:
        """Append one feed transition and retain only the newest 50."""
        self.feed_health_history.append(
            {"healthy": event.healthy, "reason": bounded_error(event.reason), "at": at.isoformat()}
        )
        if not event.healthy:
            self.last_error = bounded_error(event.reason)


@dataclass
class OutputHealth:
    """Delivery outcome state for one configured target."""

    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def record(self, ok: bool, at: datetime, error: object | None = None) -> None:
        """Update output counters from one delivery result."""
        if ok:
            self.last_success_at = at
            self.consecutive_failures = 0
        else:
            self.last_error_at = at
            self.last_error = bounded_error(error)
            self.consecutive_failures += 1


def storage_forecast(free_bytes: int, samples: list[tuple[datetime, int]]) -> float | None:
    """Estimate days to full from completed recording sizes and timestamps."""
    if free_bytes <= 0:
        return 0.0
    if len(samples) < MIN_SAMPLES:
        return None
    first, last = samples[0][0], samples[-1][0]
    seconds = (last - first).total_seconds()
    total = sum(max(0, size) for _, size in samples)
    if seconds <= 0 or total <= 0:
        return None
    return min(MAX_FORECAST_DAYS, free_bytes / (total / (seconds / 86400.0)))


def event_bus_health(bus: EventBus) -> list[dict[str, object]]:
    """Expose queue depth, drop count and oldest-event lag without consuming queues."""
    now = time.time()
    result: list[dict[str, object]] = []
    for index, subscription in enumerate(bus.subscriptions):
        queue = cast("Any", subscription.queue)
        oldest = queue._queue[0] if subscription.queue.qsize() else None
        measured = getattr(oldest, "measured_at", None) or getattr(oldest, "at", None)
        lag = max(0.0, now - measured.timestamp()) if isinstance(measured, datetime) else None
        result.append(
            {
                "id": str(index),
                "depth": subscription.queue.qsize(),
                "dropped": subscription.dropped,
                "lag_s": lag,
            }
        )
    return result


@dataclass
class StorageScanner:
    """Threaded disk scan with a maximum one-minute refresh interval."""

    recordings_root: Path
    db_path: Path
    clock: Callable[[], float] = time.monotonic
    cached: dict[str, object] | None = None
    scanned_at: float | None = None

    def scan_sync(self) -> dict[str, object]:
        """Perform the blocking filesystem scan."""
        disk_root = (
            self.recordings_root if self.recordings_root.exists() else self.recordings_root.parent
        )
        usage = shutil.disk_usage(disk_root)
        recording_size = (
            sum(path.stat().st_size for path in self.recordings_root.rglob("*") if path.is_file())
            if self.recordings_root.exists()
            else 0
        )
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        wal = Path(str(self.db_path) + "-wal")
        wal_size = wal.stat().st_size if wal.exists() else 0
        return {
            "recordings_bytes": recording_size,
            "free_bytes": usage.free,
            "db_bytes": db_size,
            "db_wal_bytes": wal_size,
        }

    async def scan(self) -> dict[str, object]:
        """Return a cached scan, refreshing it in a worker at most each minute."""
        now = self.clock()
        if (
            self.cached is None
            or self.scanned_at is None
            or now - self.scanned_at >= SCAN_INTERVAL_S
        ):
            self.cached = await asyncio.to_thread(self.scan_sync)
            self.scanned_at = now
        return self.cached
