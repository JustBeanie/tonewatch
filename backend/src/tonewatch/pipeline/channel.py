"""One source's streaming DSP and domain-event pipeline."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

import numpy as np

from tonewatch.dsp.engine import DetectionEngine
from tonewatch.events import CallClosed, ChannelLevel, EventBus, SpectrumUpdate, ToneDetected
from tonewatch.pipeline.ringbuffer import RingBuffer
from tonewatch.sources.base import AudioFrame, AudioSource, make_source

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from tonewatch.config.models import Source, ToneSet
    from tonewatch.dsp.engine import EngineOutput
    from tonewatch.dsp.matcher import Detection
    from tonewatch.pipeline.watchdog import Watchdog

WallClock = Callable[[], datetime | float]
LEVEL_INTERVAL_S = 0.2


@dataclass(frozen=True, slots=True)
class RecorderCall:
    """Immutable call identity supplied to recording hooks."""

    id: UUID
    source_id: str
    started_at: datetime
    toneset_ids: frozenset[str]


RecorderHook = Callable[..., Awaitable[None] | None]


class DetectionEngineLike(Protocol):
    """Minimal stateful engine interface needed by a channel."""

    def feed(self, samples: NDArray[np.float32]) -> EngineOutput:
        """Process one audio chunk."""
        ...


EngineFactory = Callable[[list["ToneSet"]], DetectionEngineLike]


@dataclass(slots=True)
class _OpenCall:
    id: UUID
    first_detection_s: float
    last_detection_s: float
    merge_window_s: float
    toneset_ids: set[str] = field(default_factory=set)


class Channel:
    """Connect one configured audio source to detection and domain events."""

    def __init__(
        self,
        source_config: Source,
        tonesets: list[ToneSet] | tuple[ToneSet, ...],
        bus: EventBus,
        clock: WallClock = lambda: datetime.now(UTC),
        recorder_hook: RecorderHook | None = None,
        *,
        source_factory: Callable[[Source], AudioSource] | None = None,
        engine_factory: EngineFactory | None = None,
        watchdog: Watchdog | None = None,
    ) -> None:
        """Create a channel with its source, filtered tone sets, and event bus."""
        self.source_config = source_config
        self.bus, self.clock, self.recorder_hook = bus, clock, recorder_hook
        self._source_factory = source_factory or make_source
        self._engine_factory = engine_factory or DetectionEngine
        self.watchdog = watchdog
        allowed = source_config.tonesets
        self.tonesets = tuple(
            tone for tone in tonesets if tone.enabled and (allowed == "all" or tone.id in allowed)
        )
        pre_roll = max((tone.record.pre_roll_s for tone in self.tonesets), default=10)
        # Keep enough history to compensate for detector latency before the first tone.
        self.ringbuffer = RingBuffer((pre_roll or 10) + 1)
        self._open_call: _OpenCall | None = None
        self._anchor_wall: datetime | None = None
        self._anchor_stream_s = 0.0
        self._source: AudioSource | None = None

    @property
    def source_id(self) -> str:
        """Configured source identifier."""
        return self.source_config.id

    async def run(self) -> None:
        """Run until the source ends or raises; always close it and open calls."""
        source = self._source_factory(self.source_config)
        self._source = source
        self._anchor_wall = self._as_utc(self.clock())
        self._anchor_stream_s = 0.0
        try:
            await source.open()
            engine = self._engine_factory(list(self.tonesets))
            async for frame in source:
                self._observe_frame(frame)
                self._close_expired(frame.stream_time_s)
                self.ringbuffer.extend(frame.samples, stream_time_s=frame.stream_time_s)
                output = engine.feed(frame.samples)
                self._publish_level(frame)
                if self.bus.spectrum_subscribed(self.source_id):
                    for spectrum in output.frames:
                        self.bus.publish(
                            SpectrumUpdate(
                                self.source_id,
                                spectrum.freq_hz,
                                spectrum.purity,
                                spectrum.level_dbfs,
                                (),
                                self._to_wall_time(spectrum.t_end_s),
                            )
                        )
                for detection in output.detections:
                    self._publish_detection(detection)
                if self.recorder_hook is not None:
                    call = self._recorder_call()
                    try:
                        result = self.recorder_hook(frame, self.ringbuffer, output, call, "active")
                    except TypeError:
                        result = self.recorder_hook(frame, self.ringbuffer)
                    if inspect.isawaitable(result):
                        await result
                    should_stop = getattr(self.recorder_hook, "should_stop", None)
                    if callable(should_stop) and should_stop(
                        frame.stream_time_s + frame.samples.size / 16_000, frame.samples
                    ):
                        break
                await asyncio.sleep(0)
            self._close_call()
            await asyncio.sleep(0)
        except BaseException as error:
            if self.watchdog is not None:
                self.watchdog.on_error(error)
            self._close_call()
            raise
        finally:
            await source.close()
            self._source = None

    def _publish_level(self, frame: AudioFrame) -> None:
        """Publish at most five level samples per source second."""
        last = getattr(self, "_last_level_s", -math.inf)
        if frame.stream_time_s - last < LEVEL_INTERVAL_S:
            return
        self._last_level_s = frame.stream_time_s
        samples = frame.samples
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        self.bus.publish(
            ChannelLevel(
                self.source_id,
                20 * math.log10(max(rms, 1e-12)),
                peak,
                self._to_wall_time(frame.stream_time_s),
            )
        )

    def _observe_frame(self, frame: AudioFrame) -> None:
        if self._anchor_wall is None or frame.discontinuity:
            self._anchor_wall = self._as_utc(self.clock())
            self._anchor_stream_s = frame.stream_time_s
        if self.watchdog is not None:
            self.watchdog.on_frame(frame)

    def _publish_detection(self, detection: Detection) -> None:
        toneset = next(tone for tone in self.tonesets if tone.id == detection.toneset_id)
        open_call = self._open_call
        if (
            open_call is None
            or detection.detected_at_s - open_call.last_detection_s > toneset.record.post_s
        ):
            if open_call is not None:
                self._close_call()
            open_call = _OpenCall(
                uuid4(), detection.detected_at_s, detection.detected_at_s, toneset.record.post_s
            )
            self._open_call = open_call
        else:
            open_call.merge_window_s = max(open_call.merge_window_s, toneset.record.post_s)
            open_call.last_detection_s = detection.detected_at_s
        open_call.toneset_ids.add(detection.toneset_id)
        self.bus.publish(
            ToneDetected(
                open_call.id,
                detection.toneset_id,
                self._to_wall_time(detection.detected_at_s),
                self.source_id,
            )
        )

    def _recorder_call(self) -> RecorderCall | None:
        if self._open_call is None:
            return None
        return RecorderCall(
            self._open_call.id,
            self.source_id,
            self._to_wall_time(self._open_call.first_detection_s),
            frozenset(self._open_call.toneset_ids),
        )

    def _close_expired(self, stream_time_s: float) -> None:
        if (
            self._open_call is not None
            and stream_time_s - self._open_call.last_detection_s > self._open_call.merge_window_s
        ):
            self._close_call()

    def _close_call(self) -> None:
        if self._open_call is None:
            return
        call = self._open_call
        self.bus.publish(CallClosed(call.id, "recorded", self.source_id))
        self._open_call = None

    def _to_wall_time(self, stream_time_s: float) -> datetime:
        if self._anchor_wall is None:
            raise RuntimeError("channel has not started")
        return self._anchor_wall + timedelta(seconds=stream_time_s - self._anchor_stream_s)

    @staticmethod
    def _as_utc(value: datetime | float) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return datetime.fromtimestamp(value, UTC)
