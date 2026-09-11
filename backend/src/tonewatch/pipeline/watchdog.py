"""Clock-driven feed health monitoring."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import numpy as np

from tonewatch.events import EventBus, FeedHealthChanged

if TYPE_CHECKING:
    from tonewatch.sources.base import AudioFrame, SourceError

CLIP_LEVEL = 0.999

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class Watchdog:
    """Detect feed failures and emit one event per health transition."""

    def __init__(
        self,
        source_id: str,
        bus: EventBus,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        no_data_s: float = 10,
        flatline_s: float = 300,
        clip_ratio: float = 0.05,
        window_s: float = 10,
        recovery_s: float = 1,
    ) -> None:
        """Create a clock-driven health monitor with configurable thresholds."""
        self.source_id, self.bus, self.clock, self.sleep = source_id, bus, clock, sleep
        self.no_data_s, self.flatline_s = no_data_s, flatline_s
        self.clip_ratio, self.window_s, self.recovery_s = clip_ratio, window_s, recovery_s
        self._last_frame_at: float | None = clock()
        self._flatline_started: float | None = None
        self._clips: deque[tuple[float, int, int]] = deque()
        self._unhealthy_reason: str | None = None
        self._good_since: float | None = None
        self._stopped = False

    @property
    def healthy(self) -> bool:
        """Whether the last published state is healthy."""
        return self._unhealthy_reason is None

    def on_frame(self, frame: AudioFrame) -> None:
        """Observe a frame and evaluate instantaneous feed conditions."""
        now = self.clock()
        self._last_frame_at = now
        bad = frame.discontinuity
        if frame.discontinuity:
            self._set_unhealthy("disconnect", now)
        samples = np.asarray(frame.samples, dtype=np.float32)
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0
        if rms < 10 ** (-80 / 20):
            if self._flatline_started is None:
                self._flatline_started = now
        else:
            self._flatline_started = None
        clipped = int(np.count_nonzero(np.abs(samples) >= CLIP_LEVEL))
        self._clips.append((now, clipped, samples.size))
        self._prune_clips(now)
        if self._clip_ratio() > self.clip_ratio:
            self._set_unhealthy("clipping", now)
            bad = True
        elif self._flatline_started is not None and now - self._flatline_started > self.flatline_s:
            self._set_unhealthy("flatline", now)
            bad = True
        if not bad:
            self._good_frame(now)

    def on_error(self, error: SourceError | BaseException) -> None:
        """Observe a source failure as a disconnect."""
        del error
        self._set_unhealthy("disconnect", self.clock())

    def check(self) -> None:
        """Evaluate elapsed-time conditions; callers drive this with their clock."""
        now = self.clock()
        bad = self._last_frame_at is None or now - self._last_frame_at > self.no_data_s
        if bad:
            self._set_unhealthy("no_data", now)
        elif self._flatline_started is not None and now - self._flatline_started > self.flatline_s:
            self._set_unhealthy("flatline", now)
            bad = True
        self._prune_clips(now)
        if self._clip_ratio() > self.clip_ratio:
            self._set_unhealthy("clipping", now)
            bad = True
        if not bad and self._unhealthy_reason is not None:
            self._good_frame(now)

    def _clip_ratio(self) -> float:
        total = sum(item[2] for item in self._clips)
        return sum(item[1] for item in self._clips) / total if total else 0.0

    def _prune_clips(self, now: float) -> None:
        while self._clips and now - self._clips[0][0] > self.window_s:
            self._clips.popleft()

    def _set_unhealthy(self, reason: str, now: float) -> None:
        del now
        self._good_since = None
        if self._unhealthy_reason is None:
            self._unhealthy_reason = reason
            self.bus.publish(FeedHealthChanged(self.source_id, False, reason))

    def _good_frame(self, now: float) -> None:
        if self._unhealthy_reason is None:
            return
        self._good_since = self._good_since or now
        if now - self._good_since >= self.recovery_s:
            self._unhealthy_reason = None
            self._good_since = None
            self.bus.publish(FeedHealthChanged(self.source_id, True))

    async def run(self, interval_s: float = 1) -> None:
        """Poll elapsed conditions until stopped, using only the injected sleep."""
        while not self._stopped:
            await self.sleep(interval_s)
            self.check()

    async def stop(self) -> None:
        """Stop a polling task cleanly."""
        self._stopped = True
