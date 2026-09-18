"""One source's streaming DSP and domain-event pipeline."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

import numpy as np
import structlog

from tonewatch.admin.health import ChannelHealth
from tonewatch.dsp.discovery import DiscoveryTracker, ToneCandidate
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.squelch import Squelch
from tonewatch.events import (
    CallClosed,
    ChannelLevel,
    EventBus,
    SpectrumUpdate,
    SquelchChanged,
    SquelchHealthChanged,
    ToneCandidateObserved,
    ToneDetected,
)
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
logger = structlog.get_logger("tonewatch.squelch")


@dataclass(frozen=True, slots=True)
class RecorderCall:
    """Immutable call identity supplied to recording hooks."""

    id: UUID
    source_id: str
    started_at: datetime
    toneset_ids: frozenset[str]
    drill: bool = False
    drill_keep: bool = False


class RecorderHook(Protocol):
    """Typed hook used by a channel to stream frames into a recorder."""

    def __call__(
        self,
        frame: AudioFrame,
        ring: RingBuffer,
        output: EngineOutput,
        call: RecorderCall | None,
        lifecycle: str,
    ) -> Awaitable[None] | None:
        """Accept one frame and the current call lifecycle."""
        ...


class DetectionEngineLike(Protocol):
    """Minimal stateful engine interface needed by a channel."""

    def feed(self, samples: NDArray[np.float32]) -> EngineOutput:
        """Process one audio chunk."""
        ...


class LiveHubLike(Protocol):
    """Minimal non-blocking interface used by a channel."""

    def feed(
        self,
        source_id: str,
        samples: NDArray[np.float32],
        *,
        gate_open: bool = True,
    ) -> None:
        """Accept one normalized frame without awaiting."""


EngineFactory = Callable[[list["ToneSet"]], DetectionEngineLike]


@dataclass(slots=True)
class _OpenCall:
    id: UUID
    first_detection_s: float
    last_detection_s: float
    merge_window_s: float
    toneset_ids: set[str] = field(default_factory=set)
    drill: bool = False
    drill_keep: bool = False


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
        source_settings: object | None = None,
        discovery_settings: object | None = None,
        live_hub: LiveHubLike | None = None,
        agency_lookup: Callable[[str], dict[str, object] | None] | None = None,
    ) -> None:
        """Create a channel with its source, filtered tone sets, and event bus."""
        self.source_config = source_config
        self.bus, self.clock, self.recorder_hook = bus, clock, recorder_hook
        if source_factory is not None:
            self._source_factory = source_factory
        elif source_settings is None:
            self._source_factory = make_source
        else:
            self._source_factory = lambda config: make_source(config, settings=source_settings)
        self._engine_factory = engine_factory or DetectionEngine
        self.watchdog = watchdog
        allowed = source_config.tonesets
        self.tonesets = tuple(
            tone for tone in tonesets if tone.enabled and (allowed == "all" or tone.id in allowed)
        )
        self.agency_lookup = agency_lookup or (lambda _agency_id: None)
        discovery = discovery_settings
        self.discovery = (
            DiscoveryTracker(
                max_gap_s=float(getattr(discovery, "max_gap_s", 0.5)),
                min_segment_s=float(getattr(discovery, "min_segment_s", 0.3)),
                max_segment_s=float(getattr(discovery, "max_segment_s", 3.0)),
                known_tonesets=tonesets,
            )
            if bool(getattr(discovery, "enabled", False))
            and bool(getattr(source_config, "discovery_enabled", True))
            else None
        )
        self.discovery_clip = bool(getattr(discovery, "clip", True))
        pre_roll = max((tone.record.pre_roll_s for tone in self.tonesets), default=10)
        # Keep enough history to compensate for detector latency before the first tone.
        self.ringbuffer = RingBuffer(max(pre_roll or 10, 20) + 1)
        self._open_call: _OpenCall | None = None
        self._anchor_wall: datetime | None = None
        self._anchor_stream_s = 0.0
        self._source: AudioSource | None = None
        self.live_hub = live_hub
        self._squelch = Squelch(source_config.squelch)
        self._squelch_open: bool | None = None
        self._last_activity_at: datetime | None = None
        self._level_taps: set[Callable[[float], None]] = set()
        self._drill_samples: np.ndarray | None = None
        self._drill_mode = "replace"
        self._drill_offset = 0
        self._drill_id: UUID | None = None
        self._drill_keep = False
        self._current_frame_drill = False
        self.health = ChannelHealth()

    @property
    def source_id(self) -> str:
        """Configured source identifier."""
        return self.source_config.id

    @property
    def squelch_open(self) -> bool | None:
        """Current software squelch state, or None when disabled."""
        return self._squelch_open

    @property
    def last_activity_at(self) -> datetime | None:
        """UTC time of the most recent open transition."""
        return self._last_activity_at

    @property
    def squelch(self) -> Squelch:
        """Expose the channel estimator for diagnostics and calibration."""
        return self._squelch

    def add_level_tap(self, tap: Callable[[float], None]) -> None:
        self._level_taps.add(tap)

    def remove_level_tap(self, tap: Callable[[float], None]) -> None:
        self._level_taps.discard(tap)

    @property
    def drill_active(self) -> bool:
        return self._drill_samples is not None

    async def start_drill(
        self, samples: np.ndarray, mode: str, keep: bool = False
    ) -> tuple[UUID, float]:
        """Schedule a waveform on this running channel without restarting it."""
        if mode not in {"mix", "replace"}:
            raise ValueError("mode must be mix or replace")
        if self.drill_active:
            raise RuntimeError("drill already active")
        self._drill_samples = np.asarray(samples, dtype=np.float32).copy()
        self._drill_mode = mode
        self._drill_offset = 0
        self._drill_id = uuid4()
        self._drill_keep = keep
        return self._drill_id, self._drill_samples.size / 16_000

    def _apply_drill(self, samples: np.ndarray) -> np.ndarray:
        if self._drill_samples is None:
            self._current_frame_drill = False
            return samples
        left = self._drill_offset
        right = min(left + samples.size, self._drill_samples.size)
        injected = self._drill_samples[left:right]
        self._drill_offset = right
        if injected.size == 0:
            self._drill_samples = None
            self._current_frame_drill = False
            return samples
        self._current_frame_drill = True
        result = np.asarray(samples, dtype=np.float32).copy()
        if self._drill_mode == "replace":
            result[: injected.size] = injected
        else:
            result[: injected.size] = np.clip(
                result[: injected.size] * np.float32(0.5) + injected * np.float32(0.5), -1.0, 1.0
            )
        if right >= self._drill_samples.size:
            self._drill_samples = None
        return result

    async def run(  # noqa: PLR0912,PLR0915 -- ordered stream lifecycle is intentionally explicit
        self,
    ) -> None:
        """Run until the source ends or raises; always finish open recordings."""
        source = self._source_factory(self.source_config)
        self._source = source
        self._anchor_wall = self._as_utc(self.clock())
        self._anchor_stream_s = 0.0
        try:
            await source.open()
            engine = self._engine_factory(list(self.tonesets))
            async for raw_frame in source:
                frame = AudioFrame(
                    self._apply_drill(raw_frame.samples),
                    raw_frame.stream_time_s,
                    raw_frame.source_id,
                    raw_frame.discontinuity,
                )
                self._observe_frame(frame)
                await self._close_expired(frame.stream_time_s)
                self.ringbuffer.extend(frame.samples, stream_time_s=frame.stream_time_s)
                started_dsp = time.perf_counter()
                output = engine.feed(frame.samples)
                self.health.observe_frame(
                    frame.samples.size / 16_000,
                    time.perf_counter() - started_dsp,
                    dropped=int(getattr(source, "dropped", 0)) - getattr(self, "_last_dropped", 0),
                )
                self._last_dropped = int(getattr(source, "dropped", 0))
                stop_on_squelch = False
                for spectrum in output.frames:
                    state, changed = self._squelch.feed(spectrum.level_dbfs, spectrum.t_end_s)
                    self._squelch_open = state if self.source_config.squelch.mode != "off" else None
                    if changed:
                        at = self._to_wall_time(spectrum.t_end_s)
                        if state:
                            self._last_activity_at = at
                        self.bus.publish(
                            SquelchChanged(self.source_id, state, spectrum.level_dbfs, at)
                        )
                    if self._squelch.health_changed:
                        stuck, chatter = self._squelch.health()
                        self.bus.publish(SquelchHealthChanged(self.source_id, stuck, chatter, at))
                        logger.log(
                            "warning" if stuck or chatter else "info",
                            "squelch health changed",
                            source_id=self.source_id,
                            stuck_open=stuck,
                            chatter=chatter,
                        )
                    self._update_watchdog_squelch(state)
                    if not state and changed and self._stop_on_squelch:
                        stop_on_squelch = True
                self._feed_live(
                    frame,
                    gate_open=(
                        self.source_config.squelch.mode == "off"
                        or self._squelch.calibrating
                        or self._squelch_open is True
                    ),
                )
                if self.discovery is not None:
                    for candidate in self.discovery.feed(
                        output.segment_update,
                        output.detections,
                        frame.stream_time_s + frame.samples.size / 16_000,
                    ):
                        self.bus.publish(
                            ToneCandidateObserved(
                                candidate,
                                self.source_id,
                                self._to_wall_time(candidate.end_s),
                                self._candidate_clip(candidate) if self.discovery_clip else None,
                            )
                        )
                level = output.frames[-1].level_dbfs if output.frames else None
                self._publish_level(frame, level)
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
                    await self._publish_detection(detection)
                if self.recorder_hook is not None:
                    call = self._recorder_call()
                    result = self.recorder_hook(frame, self.ringbuffer, output, call, "active")
                    if inspect.isawaitable(result):
                        await result
                    should_stop = getattr(self.recorder_hook, "should_stop", None)
                    if callable(should_stop) and should_stop(
                        frame.stream_time_s + frame.samples.size / 16_000, frame.samples
                    ):
                        await self._close_call()
                if stop_on_squelch:
                    await self._close_call()
                await asyncio.sleep(0)
            await self._close_call()
            await asyncio.sleep(0)
        except BaseException as error:
            if self.watchdog is not None:
                self.watchdog.on_error(error)
            await self._close_call()
            raise
        finally:
            await source.close()
            self._source = None

    def _feed_live(self, frame: AudioFrame, *, gate_open: bool) -> None:
        if self.live_hub is not None:
            self.live_hub.feed(self.source_id, frame.samples, gate_open=gate_open)

    def _publish_level(self, frame: AudioFrame, level_dbfs: float | None = None) -> None:
        """Publish at most five level samples per source second."""
        last = getattr(self, "_last_level_s", -math.inf)
        if frame.stream_time_s - last < LEVEL_INTERVAL_S:
            return
        self._last_level_s = frame.stream_time_s
        samples = frame.samples
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        squelch = getattr(self, "_squelch", None)
        mode = getattr(getattr(self.source_config, "squelch", None), "mode", "off")
        self.bus.publish(
            ChannelLevel(
                self.source_id,
                20 * math.log10(max(rms, 1e-12)),
                peak,
                self._to_wall_time(frame.stream_time_s),
                getattr(self, "_squelch_open", None),
                level_dbfs if mode != "off" else None,
                mode if mode != "off" else None,
                squelch.noise_floor if squelch is not None else None,
                squelch.open_threshold_dbfs if squelch is not None and mode != "off" else None,
                squelch.close_threshold_dbfs if squelch is not None and mode != "off" else None,
                squelch.calibrating if squelch is not None and mode != "off" else None,
                squelch.stuck_open if squelch is not None and mode != "off" else None,
                squelch.chatter if squelch is not None and mode != "off" else None,
                squelch.transitions_per_min if squelch is not None and mode != "off" else None,
            )
        )
        health = getattr(self, "health", None)
        if health is not None:
            health.level = {"rms_dbfs": 20 * math.log10(max(rms, 1e-12)), "peak": peak}
            health.squelch_open = getattr(self, "_squelch_open", None)
        if level_dbfs is not None:
            for tap in tuple(getattr(self, "_level_taps", ())):
                tap(level_dbfs)

    def _candidate_clip(self, candidate: ToneCandidate) -> bytes | None:
        """Return the retained candidate window for persistence-side encoding."""
        samples, start_s = self.ringbuffer.snapshot_with_time()
        end_s = self.ringbuffer.end_stream_time_s
        if start_s is None or end_s is None:
            return None
        candidate_start = max(candidate.start_s, start_s)
        candidate_end = min(candidate.end_s + 15.0, end_s)
        left = max(0, round((candidate_start - start_s) * self.ringbuffer.sample_rate))
        right = min(samples.size, round((candidate_end - start_s) * self.ringbuffer.sample_rate))
        if right <= left:
            return None
        return samples[left:right].tobytes()

    def _observe_frame(self, frame: AudioFrame) -> None:
        if self._anchor_wall is None or frame.discontinuity:
            self._anchor_wall = self._as_utc(self.clock())
            self._anchor_stream_s = frame.stream_time_s
        if self.watchdog is not None:
            set_rtl_squelch = getattr(self.watchdog, "set_rtl_squelch", None)
            if callable(set_rtl_squelch):
                set_rtl_squelch(getattr(self.source_config, "rtl_fm_squelch", 0) > 0)
            self.watchdog.on_frame(frame)

    def _update_watchdog_squelch(self, state: bool) -> None:
        """Pass software squelch state without replacing hardware squelch state."""
        if self.watchdog is None:
            return
        set_squelch_open = getattr(self.watchdog, "set_squelch_open", None)
        if callable(set_squelch_open):
            set_squelch_open(state if self.source_config.squelch.mode != "off" else None)

    async def _publish_detection(self, detection: Detection) -> None:
        toneset = next(tone for tone in self.tonesets if tone.id == detection.toneset_id)
        open_call = self._open_call
        if (
            open_call is None
            or detection.detected_at_s - open_call.last_detection_s > toneset.record.post_s
        ):
            if open_call is not None:
                await self._close_call()
            open_call = _OpenCall(
                uuid4(), detection.detected_at_s, detection.detected_at_s, toneset.record.post_s
            )
            self._open_call = open_call
        else:
            open_call.merge_window_s = max(open_call.merge_window_s, toneset.record.post_s)
            open_call.last_detection_s = detection.detected_at_s
        open_call.toneset_ids.add(detection.toneset_id)
        open_call.drill = open_call.drill or self._current_frame_drill
        open_call.drill_keep = open_call.drill_keep or self._drill_keep
        self.bus.publish(
            ToneDetected(
                open_call.id,
                detection.toneset_id,
                self._to_wall_time(detection.detected_at_s),
                self.source_id,
                open_call.drill,
                self.agency_lookup(toneset.agency_id) if toneset.agency_id is not None else None,
                open_call.drill,
                open_call.drill_keep,
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
            self._open_call.drill,
            self._open_call.drill_keep,
        )

    @property
    def _stop_on_squelch(self) -> bool:
        """Whether an active tone set requests squelch-driven post-roll stop."""
        return (
            self.source_config.squelch.mode != "off"
            and self._open_call is not None
            and all(
                next(tone for tone in self.tonesets if tone.id == tone_id).record.stop_on_squelch
                for tone_id in self._open_call.toneset_ids
            )
        )

    async def _close_expired(self, stream_time_s: float) -> None:
        if (
            self._open_call is not None
            and stream_time_s - self._open_call.last_detection_s > self._open_call.merge_window_s
        ):
            await self._close_call()

    async def _close_call(self) -> None:
        if self._open_call is None:
            return
        call = self._open_call
        self._open_call = None
        finish = getattr(self.recorder_hook, "finish", None)
        if callable(finish):
            result = finish()
            if inspect.isawaitable(result):
                await result
        else:
            self.bus.publish(CallClosed(call.id, "recorded", self.source_id))

    def _to_wall_time(self, stream_time_s: float) -> datetime:
        if self._anchor_wall is None:
            raise RuntimeError("channel has not started")
        return self._anchor_wall + timedelta(seconds=stream_time_s - self._anchor_stream_s)

    @staticmethod
    def _as_utc(value: datetime | float) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return datetime.fromtimestamp(value, UTC)
