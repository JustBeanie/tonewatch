"""M3.6/M3.7 pipeline contract tests."""

import asyncio
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast
from uuid import uuid4

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select

from tonewatch.config.models import (
    AdminAlertsConfig,
    AppConfig,
    FileSource,
    RecordingPolicy,
    RtlSdrSource,
    ToneSet,
    ToneSpec,
)
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.matcher import Detection
from tonewatch.dsp.spectrum import SpectrumFrame
from tonewatch.dsp.squelch import SquelchConfig
from tonewatch.events import (
    CallClosed,
    ChannelLevel,
    Event,
    EventBus,
    FeedHealthChanged,
    SquelchChanged,
    ToneDetected,
)
from tonewatch.pipeline.channel import Channel, RecorderCall
from tonewatch.pipeline.persistence import PersistenceSubscriber, _relative_path
from tonewatch.pipeline.ringbuffer import RingBuffer
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.pipeline.watchdog import Watchdog
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import Call, CallToneSet


def _toneset(toneset_id: str, *, post_s: float = 3, agency_id: str | None = None) -> ToneSet:
    return ToneSet(
        id=toneset_id,
        name=toneset_id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
        record=RecordingPolicy(post_s=post_s),
        agency_id=agency_id,
    )


@given(
    chunks=st.lists(
        st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=30),
        min_size=1,
        max_size=20,
    ),
    seconds=st.integers(min_value=0, max_value=100),
)
def test_ring_buffer_snapshot_is_last_samples(chunks: list[list[int]], seconds: int) -> None:
    ring = RingBuffer(capacity_s=1, sample_rate=100)
    written: list[int] = []
    for chunk in chunks:
        ring.extend(np.asarray(chunk, dtype=np.float32), stream_time_s=len(written) / 100)
        written.extend(chunk)
    count = min(len(written), seconds * 100, ring.capacity_samples)
    expected = np.asarray(written[-count:] if count else [], dtype=np.float32)
    np.testing.assert_array_equal(ring.snapshot(seconds), expected)


def test_ring_buffer_tracks_stream_time_and_capacity() -> None:
    ring = RingBuffer(capacity_s=1, sample_rate=10)
    ring.extend(np.arange(15, dtype=np.float32), stream_time_s=2)
    assert ring.start_stream_time_s == 2.5
    assert ring.end_stream_time_s == 3.5
    np.testing.assert_array_equal(ring.snapshot(0.5), np.arange(10, 15, dtype=np.float32))


def test_ring_buffer_validates_empty_and_discontinuous_inputs() -> None:
    with np.testing.assert_raises(ValueError):
        RingBuffer(capacity_s=0)
    ring = RingBuffer(capacity_s=1, sample_rate=10)
    ring.extend(np.zeros(0, dtype=np.float32))
    ring.extend(np.arange(4, dtype=np.float32), stream_time_s=5)
    ring.extend(np.asarray([9], dtype=np.float32), stream_time_s=20)
    assert ring.size == 1
    with np.testing.assert_raises(ValueError):
        ring.snapshot(-1)
    samples, start = ring.snapshot_with_time()
    assert start == 20 and samples.size == 1


def test_ring_buffer_defaults_missing_stream_time_and_reports_empty_timestamp() -> None:
    ring = RingBuffer(capacity_s=1, sample_rate=10)
    ring.extend(np.asarray([1, 2], dtype=np.float32))
    assert ring.end_stream_time_s == 0.2
    empty = RingBuffer(capacity_s=1, sample_rate=10)
    samples, start = empty.snapshot_with_time()
    assert samples.size == 0 and start is None


def test_ring_buffer_wraps_partial_chunk_without_losing_order() -> None:
    ring = RingBuffer(capacity_s=1, sample_rate=4)
    ring.extend(np.asarray([1, 2, 3], dtype=np.float32))
    ring.extend(np.asarray([4, 5, 6], dtype=np.float32))
    np.testing.assert_array_equal(ring.snapshot(), np.asarray([3, 4, 5, 6], dtype=np.float32))


class _Source:
    def __init__(self, frames: list[AudioFrame], error: BaseException | None = None) -> None:
        self.frames = frames
        self.error = error
        self.closed = False

    async def open(self) -> None:
        return

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for frame in self.frames:
            yield frame
        if self.error:
            raise self.error


class _InfiniteSource:
    def __init__(self) -> None:
        self.closed = False
        self.position = 0

    async def open(self) -> None:
        return

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> AudioFrame:
        frame = _frame("radio", self.position / 10)
        self.position += 1
        return frame


class _Engine:
    outputs: ClassVar[list[EngineOutput]] = []

    def __init__(self, tonesets: list[ToneSet]) -> None:
        del tonesets

    def feed(self, samples: np.ndarray) -> EngineOutput:
        del samples
        return self.outputs.pop(0)


def _detection(toneset_id: str, at: float) -> Detection:
    return Detection(toneset_id, at, (), True)


def _frame(source_id: str, at: float, *, discontinuity: bool = False) -> AudioFrame:
    return AudioFrame(np.zeros(1600, dtype=np.float32), at, source_id, discontinuity)


def _spectrum(level_dbfs: float, at: float) -> SpectrumFrame:
    return SpectrumFrame(at, 1000, level_dbfs, 1.0, True)


def test_channel_wires_squelch_level_and_never_gates_detection() -> None:
    async def run(config: Any, output: EngineOutput) -> list[Event]:
        source = _Source([_frame("radio", 0)])
        bus = EventBus()
        subscription = bus.subscribe()
        channel = Channel(
            config,
            [_toneset("page")],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
        )
        _Engine.outputs = [output]
        await channel.run()
        await asyncio.sleep(0)
        events: list[Event] = []
        while not subscription.queue.empty():
            events.append(cast("Any", subscription.queue.get_nowait()))
        return events

    async def scenario() -> None:
        detected = _detection("page", 1.25)
        enabled = FileSource(
            id="radio",
            name="radio",
            path="unused.wav",
            squelch=SquelchConfig(mode="level", open_dbfs=-10, close_dbfs=-20),
        )
        enabled_events = await run(
            enabled,
            EngineOutput((_spectrum(-30, 0.3),), (), (detected,)),
        )
        levels = [event for event in enabled_events if isinstance(event, ChannelLevel)]
        detections = [event for event in enabled_events if isinstance(event, ToneDetected)]
        assert levels and levels[0].squelch_level_dbfs == -30
        assert levels[0].rms_dbfs == pytest.approx(-240, abs=1)
        assert detections and detections[0].detected_at == datetime(
            2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC
        )

        disabled = FileSource(id="radio", name="radio", path="unused.wav")
        disabled_events = await run(
            disabled,
            EngineOutput((_spectrum(-30, 0.3),), (), (detected,)),
        )
        off_level = next(event for event in disabled_events if isinstance(event, ChannelLevel))
        off_detection = next(event for event in disabled_events if isinstance(event, ToneDetected))
        assert off_level.squelch_level_dbfs is None
        assert off_detection.detected_at == detections[0].detected_at

    asyncio.run(scenario())


def test_channel_live_gate_follows_squelch_without_gating_detection() -> None:
    class Hub:
        def __init__(self) -> None:
            self.gates: list[bool] = []

        def feed(self, source_id: str, samples: np.ndarray, *, gate_open: bool = True) -> None:
            del source_id, samples
            self.gates.append(gate_open)

    async def run(config: Any, outputs: list[EngineOutput]) -> tuple[list[bool], list[datetime]]:
        source = _Source([_frame("radio", n) for n in (0, 1, 2)])
        hub = Hub()
        bus = EventBus()
        subscription = bus.subscribe(ToneDetected)
        _Engine.outputs = list(outputs)
        await Channel(
            config,
            [_toneset("page")],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
            live_hub=cast("Any", hub),
        ).run()
        await asyncio.sleep(0)
        detections = [
            cast("ToneDetected", subscription.queue.get_nowait())
            for _ in range(subscription.queue.qsize())
        ]
        return hub.gates, [event.detected_at for event in detections]

    async def scenario() -> None:
        outputs = [
            EngineOutput((_spectrum(-60, 0.3),), (), (_detection("page", 0.1),)),
            EngineOutput((_spectrum(-30, 1.3),), (), ()),
            EngineOutput((_spectrum(-60, 2.3),), (), ()),
        ]
        off_gates, off_times = await run(
            FileSource(id="radio", name="radio", path="unused.wav"), outputs
        )
        level_gates, level_times = await run(
            FileSource(
                id="radio",
                name="radio",
                path="unused.wav",
                squelch=SquelchConfig(
                    mode="level", open_dbfs=-40, close_dbfs=-45, attack_ms=0, hang_ms=0
                ),
            ),
            outputs,
        )
        assert off_gates == [True, True, True]
        assert level_gates == [False, True, False]
        assert level_times == off_times

    asyncio.run(scenario())


def test_channel_auto_squelch_calibrates_without_gating_detection() -> None:
    class Hub:
        def __init__(self) -> None:
            self.gates: list[bool] = []

        def feed(self, source_id: str, samples: np.ndarray, *, gate_open: bool = True) -> None:
            del source_id, samples
            self.gates.append(gate_open)

    async def run(config: Any) -> tuple[list[bool], list[datetime]]:
        source = _Source([_frame("radio", n) for n in (0, 1, 2)])
        bus = EventBus()
        hub = Hub()
        subscription = bus.subscribe(ToneDetected)
        _Engine.outputs = [
            EngineOutput((_spectrum(-70, 0.3),), (), (_detection("page", 0.1),)),
            EngineOutput((_spectrum(-30, 5.3),), (), ()),
            EngineOutput((_spectrum(-120, 6.3),), (), ()),
        ]
        await Channel(
            config,
            [_toneset("page")],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
            live_hub=cast("Any", hub),
        ).run()
        await asyncio.sleep(0)
        times = [
            cast("ToneDetected", subscription.queue.get_nowait()).detected_at
            for _ in range(subscription.queue.qsize())
        ]
        return hub.gates, times

    async def scenario() -> None:
        off_gates, off_times = await run(FileSource(id="radio", name="radio", path="unused.wav"))
        auto_gates, auto_times = await run(
            FileSource(
                id="radio",
                name="radio",
                path="unused.wav",
                squelch=SquelchConfig(mode="auto", auto_min_samples_s=5, attack_ms=0, hang_ms=0),
            )
        )
        assert off_gates == [True, True, True]
        assert auto_gates == [True, True, False]
        assert auto_times == off_times

    asyncio.run(scenario())


def test_channel_auto_squelch_keeps_agency_on_detection() -> None:
    async def run() -> ToneDetected:
        source = _Source([_frame("radio", 0)])
        bus = EventBus()
        subscription = bus.subscribe(ToneDetected)
        _Engine.outputs = [EngineOutput((_spectrum(-30, 0.3),), (), (_detection("page", 0.1),))]
        await Channel(
            FileSource(
                id="radio",
                name="radio",
                path="unused.wav",
                squelch=SquelchConfig(mode="auto", auto_min_samples_s=5),
            ),
            [_toneset("page", agency_id="fire")],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
            agency_lookup=lambda agency_id: {"id": agency_id, "name": "Fire"},
        ).run()
        await asyncio.sleep(0)
        return cast("ToneDetected", subscription.queue.get_nowait())

    event = asyncio.run(run())
    assert event.agency == {"id": "fire", "name": "Fire"}


def test_channel_watchdog_flatline_respects_software_and_rtl_squelch() -> None:
    async def run(config: Any, outputs: list[EngineOutput]) -> list[FeedHealthChanged]:
        now = [0.0]
        bus = EventBus()
        subscription = bus.subscribe(FeedHealthChanged)
        watchdog = Watchdog("radio", bus, clock=lambda: now[0], flatline_s=5)
        source = _Source([_frame("radio", 0), _frame("radio", 3), _frame("radio", 6)])
        channel = Channel(
            config,
            [],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
            watchdog=watchdog,
        )
        _Engine.outputs = outputs
        await channel.run()
        now[0] = 6
        watchdog.check()
        await asyncio.sleep(0)
        events: list[FeedHealthChanged] = []
        while not subscription.queue.empty():
            events.append(cast("Any", subscription.queue.get_nowait()))
        return events

    async def scenario() -> None:
        def silent() -> list[EngineOutput]:
            return [EngineOutput((), (), ())] * 3

        off = FileSource(id="radio", name="radio", path="unused.wav")
        assert any(event.reason == "flatline" for event in await run(off, silent()))

        closed = FileSource(
            id="radio",
            name="radio",
            path="unused.wav",
            squelch=SquelchConfig(mode="level", open_dbfs=-10, close_dbfs=-20),
        )
        low = [EngineOutput((_spectrum(-60, n),), (), ()) for n in (0.3, 3.3, 6.3)]
        assert not any(event.reason == "flatline" for event in await run(closed, low))

        rtl = RtlSdrSource(id="radio", name="radio", freq_hz=154000000, rtl_fm_squelch=4)
        assert not any(event.reason == "flatline" for event in await run(rtl, silent()))

    asyncio.run(scenario())


def test_channel_squelch_changed_is_transition_only() -> None:
    async def run() -> None:
        source = _Source([_frame("radio", n) for n in (0, 1, 2)])
        bus = EventBus()
        subscription = bus.subscribe(SquelchChanged)
        config = FileSource(
            id="radio",
            name="radio",
            path="unused.wav",
            squelch=SquelchConfig(mode="level", open_dbfs=-40, close_dbfs=-45, attack_ms=0),
        )
        _Engine.outputs = [
            EngineOutput((_spectrum(-30, 0.3),), (), ()),
            EngineOutput((_spectrum(-30, 1.3),), (), ()),
            EngineOutput((_spectrum(-30, 2.3),), (), ()),
        ]
        await Channel(
            config,
            [],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
        ).run()
        await asyncio.sleep(0)
        events: list[SquelchChanged] = []
        while not subscription.queue.empty():
            events.append(cast("Any", subscription.queue.get_nowait()))
        assert len(events) == 1

    asyncio.run(run())


def test_stop_on_squelch_finishes_at_hang_and_stacked_mixed_policy_is_normal() -> None:
    class Hook:
        def __init__(self) -> None:
            self.current_frame_s = -1.0
            self.finished_at: list[float] = []

        def __call__(self, frame: AudioFrame, *_args: Any) -> None:
            self.current_frame_s = frame.stream_time_s

        async def finish(self) -> None:
            self.finished_at.append(self.current_frame_s)

    async def run(stop_on_squelch: bool) -> float:
        source = _Source([_frame("radio", n) for n in (0, 0.5, 1, 2)])
        bus = EventBus()
        tone = ToneSet(
            id="page",
            name="page",
            sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
            record=RecordingPolicy(post_s=10, stop_on_squelch=stop_on_squelch),
        )
        hook = Hook()
        _Engine.outputs = [
            EngineOutput((_spectrum(-30, 0.3),), (), (_detection("page", 0.1),)),
            EngineOutput((_spectrum(-50, 0.8),), (), ()),
            EngineOutput((_spectrum(-50, 1.1),), (), ()),
            EngineOutput((_spectrum(-50, 2.1),), (), ()),
        ]
        config = FileSource(
            id="radio",
            name="radio",
            path="unused.wav",
            squelch=SquelchConfig(
                mode="level", open_dbfs=-40, close_dbfs=-45, attack_ms=0, hang_ms=200
            ),
        )
        await Channel(
            config,
            [tone],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            source_factory=cast("Any", lambda _: source),
            recorder_hook=cast("Any", hook),
        ).run()
        assert len(hook.finished_at) == 1
        return hook.finished_at[0]

    async def scenario() -> None:
        assert await run(True) == 1
        assert await run(False) == 2

        first = ToneSet(
            id="first",
            name="first",
            sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
            record=RecordingPolicy(stop_on_squelch=True),
        )
        second = ToneSet(
            id="second",
            name="second",
            sequence=[ToneSpec(freq_hz=1100, min_s=0.1)],
            record=RecordingPolicy(stop_on_squelch=False),
        )
        channel = Channel(
            FileSource(
                id="radio",
                name="radio",
                path="unused.wav",
                squelch=SquelchConfig(mode="level"),
            ),
            [first, second],
            EventBus(),
        )
        channel._anchor_wall = datetime(2026, 1, 1, tzinfo=UTC)
        await channel._publish_detection(_detection("first", 1))
        await channel._publish_detection(_detection("second", 1.1))
        assert not channel._stop_on_squelch

    asyncio.run(scenario())


def test_channel_publishes_tones_and_groups_stacked_calls(monkeypatch) -> None:
    async def run() -> list[Event]:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        frames = [_frame("radio", 0), _frame("radio", 1), _frame("radio", 6)]
        source = _Source(frames)
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = [
            EngineOutput((), (), (_detection("a", 1),)),
            EngineOutput((), (), (_detection("b", 2),)),
            EngineOutput((), (), (_detection("a", 6),)),
        ]
        bus = EventBus()
        subscription = bus.subscribe()
        channel = Channel(
            source_config,
            [_toneset("a"), _toneset("b")],
            bus,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
        )
        await channel.run()
        events: list[Event] = []
        while not subscription.queue.empty():
            events.append(subscription.queue.get_nowait())
        detected = [event for event in events if isinstance(event, ToneDetected)]
        closed = [event for event in events if isinstance(event, CallClosed)]
        assert len({event.call_id for event in detected}) == 2
        assert detected[0].detected_at == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        assert detected[1].call_id == detected[0].call_id
        assert len(closed) == 2
        return events

    asyncio.run(run())


def test_channel_replaces_open_call_and_forwards_source_errors(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        source = _Source([_frame("radio", 0)], SourceUnavailable("lost"))
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = [
            EngineOutput((), (), (_detection("a", 1), _detection("a", 5))),
        ]

        class WatchdogFake:
            def __init__(self) -> None:
                self.frames = 0
                self.errors = 0

            def on_frame(self, frame: AudioFrame) -> None:
                del frame
                self.frames += 1

            def on_error(self, error: BaseException) -> None:
                del error
                self.errors += 1

        watchdog = WatchdogFake()
        channel = Channel(
            source_config,
            [_toneset("a")],
            EventBus(),
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            engine_factory=_Engine,
            watchdog=cast("Any", watchdog),
        )
        try:
            await channel.run()
        except SourceUnavailable:
            pass
        else:
            raise AssertionError("source error was swallowed")
        assert source.closed and watchdog.frames == 1 and watchdog.errors == 1
        unstarted = Channel(source_config, [_toneset("a")], EventBus())
        with np.testing.assert_raises(RuntimeError):
            unstarted._to_wall_time(0)

    asyncio.run(run())


def test_channel_filters_disabled_and_source_restricted_tonesets(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav", tonesets=["a"])
        source = _Source([_frame("radio", 0)])
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        seen: list[tuple[ToneSet, ...]] = []

        class Engine:
            def __init__(self, tonesets: list[ToneSet]) -> None:
                seen.append(tuple(tonesets))

            def feed(self, samples: np.ndarray) -> EngineOutput:
                del samples
                return EngineOutput((), (), ())

        channel = Channel(
            source_config,
            [_toneset("a"), _toneset("b", post_s=1)],
            EventBus(),
            clock=lambda: datetime.now(UTC),
            engine_factory=Engine,
        )
        await channel.run()
        assert [item.id for item in seen[0]] == ["a"]

    asyncio.run(run())


def test_channel_calls_recorder_hook_for_frames_and_reanchors_on_discontinuity(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        source = _Source([_frame("radio", 0), _frame("radio", 5, discontinuity=True)])
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = [
            EngineOutput((), (), (_detection("a", 0.1),)),
            EngineOutput((), (), (_detection("a", 5.1),)),
        ]
        walls = iter((datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)))
        seen: list[tuple[AudioFrame, RingBuffer]] = []

        async def hook(
            frame: AudioFrame,
            ring: RingBuffer,
            output: EngineOutput,
            call: object,
            lifecycle: str,
        ) -> None:
            del output, call, lifecycle
            seen.append((frame, ring))

        bus = EventBus()
        subscription = bus.subscribe(ToneDetected)
        channel = Channel(
            source_config,
            [_toneset("a")],
            bus,
            clock=lambda: next(walls),
            recorder_hook=hook,
            engine_factory=_Engine,
        )
        await channel.run()
        detections: list[ToneDetected] = []
        for _ in range(2):
            event = subscription.queue.get_nowait()
            assert isinstance(event, ToneDetected)
            detections.append(event)
        assert len(seen) == 2 and seen[0][1] is seen[1][1]
        assert detections[1].detected_at == datetime(2026, 1, 2, 0, 0, 0, 100000, tzinfo=UTC)

    asyncio.run(run())


def test_channel_loop_yields_under_runaway_source(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        source = _InfiniteSource()
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = []
        channel = Channel(source_config, [_toneset("a")], EventBus(), engine_factory=_Engine)
        task = asyncio.create_task(channel.run())
        marker = asyncio.Event()

        async def mark() -> None:
            await asyncio.sleep(0.01)
            marker.set()

        marker_task = asyncio.create_task(mark())
        await asyncio.wait_for(marker.wait(), 0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await marker_task
        assert source.closed

    asyncio.run(run())


def test_recorder_hook_type_error_propagates(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        source = _Source([_frame("radio", 0)])
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = [EngineOutput((), (), ())]

        calls = 0

        def hook(
            frame: AudioFrame,
            ring: RingBuffer,
            output: EngineOutput | None = None,
            call: RecorderCall | None = None,
            lifecycle: str = "active",
        ) -> None:
            nonlocal calls
            del frame, ring, call, lifecycle
            calls += 1
            if output is not None:
                raise TypeError("hook failed")

        channel = Channel(
            source_config,
            [_toneset("a")],
            EventBus(),
            recorder_hook=hook,
            engine_factory=_Engine,
        )
        with np.testing.assert_raises_regex(TypeError, "hook failed"):
            await channel.run()

    asyncio.run(run())


def test_channel_finalizes_recording_on_source_error(monkeypatch) -> None:
    async def run() -> None:
        source_config = FileSource(id="radio", name="radio", path="unused.wav")
        source = _Source([_frame("radio", 0)], SourceUnavailable("lost"))
        monkeypatch.setattr("tonewatch.pipeline.channel.make_source", lambda _: source)
        _Engine.outputs = [EngineOutput((), (), (_detection("a", 0.1),))]
        finished = 0

        class Hook:
            async def __call__(
                self,
                frame: AudioFrame,
                ring: RingBuffer,
                output: EngineOutput,
                call: object,
                lifecycle: str,
            ) -> None:
                del frame, ring, output, call, lifecycle

            async def finish(self) -> None:
                nonlocal finished
                finished += 1

        channel = Channel(
            source_config,
            [_toneset("a")],
            EventBus(),
            recorder_hook=Hook(),
            engine_factory=_Engine,
        )
        with np.testing.assert_raises(SourceUnavailable):
            await channel.run()
        assert finished == 1

    asyncio.run(run())


def test_supervisor_restarts_transient_source_with_injected_sleep(monkeypatch) -> None:
    async def run() -> None:
        config = AppConfig(sources=[FileSource(id="radio", name="radio", path="x.wav")])
        delays: list[float] = []
        attempts = 0

        class ChannelFake:
            def __init__(self, *args: object, **kwargs: object) -> None:
                del args, kwargs

            async def run(self) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise SourceUnavailable("offline")

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr("tonewatch.pipeline.supervisor.Channel", ChannelFake)
        supervisor = Supervisor(
            config,
            EventBus(),
            None,
            clock=lambda: 0.0,
            sleep=fake_sleep,
            jitter=lambda delay: delay,
        )
        await supervisor.start()
        await supervisor.wait()
        assert delays == [1, 2]
        assert attempts == 3
        assert supervisor.health["radio"].restarts == 2
        assert supervisor.health["radio"].last_restart_at is not None
        await supervisor.stop()

    asyncio.run(run())


def test_supervisor_isolates_config_failure_and_reload_keeps_unchanged(monkeypatch) -> None:
    async def run() -> None:
        source_a = FileSource(id="a", name="a", path="a.wav")
        source_b = FileSource(id="b", name="b", path="b.wav")
        config = AppConfig(sources=[source_a, source_b])
        bus = EventBus()
        health = bus.subscribe(FeedHealthChanged)
        done = asyncio.Event()
        created: list[str] = []

        class ChannelFake:
            def __init__(self, source: FileSource, *args: object, **kwargs: object) -> None:
                del args, kwargs
                self.source = source
                self.cancelled = False
                created.append(source.id)

            async def run(self) -> None:
                if self.source.id == "a":
                    raise SourceConfigError("bad config")
                done.set()

        monkeypatch.setattr("tonewatch.pipeline.supervisor.Channel", ChannelFake)
        supervisor = Supervisor(
            config, bus, None, clock=lambda: 0.0, sleep=lambda _: asyncio.sleep(0)
        )
        await supervisor.start()
        await asyncio.wait_for(done.wait(), 1)
        await supervisor.wait()
        assert created == ["a", "b"]
        await asyncio.sleep(0)
        event = await health.__anext__()
        assert isinstance(event, FeedHealthChanged) and event.source_id == "a"
        await supervisor.reload(AppConfig(sources=[source_b]))
        assert created == ["a", "b"]
        await supervisor.stop()

    asyncio.run(run())


def test_persistence_writes_calls_and_tone_sets(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'calls.sqlite'}")
        await create_database_schema(engine)
        bus = EventBus()
        persistence = PersistenceSubscriber(bus, sessions)
        await persistence.start()
        call_id = uuid4()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        bus.publish(ToneDetected(call_id, "a", now, "radio"))
        bus.publish(ToneDetected(call_id, "b", now + timedelta(seconds=1), "radio"))
        bus.publish(CallClosed(call_id, "recorded", "radio"))
        await persistence.drain()
        await persistence.stop()
        async with sessions() as session:
            calls = (await session.scalars(select(Call))).all()
            tones = (await session.scalars(select(CallToneSet))).all()
        assert len(calls) == 1 and calls[0].source_id == "radio" and calls[0].status == "recorded"
        assert {tone.toneset_id for tone in tones} == {"a", "b"}
        await engine.dispose()

    asyncio.run(run())


def test_persistence_without_database_is_a_clean_noop() -> None:
    async def run() -> None:
        persistence = PersistenceSubscriber(EventBus(), None)
        await persistence.start()
        await persistence.drain()
        await persistence.stop()

    asyncio.run(run())


def test_persistence_stop_while_busy_leaves_no_pending_tasks(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'busy.sqlite'}")
        await create_database_schema(engine)

        class SlowSession:
            def __init__(self) -> None:
                self.context = sessions()
                self.session: Any = None

            async def __aenter__(self) -> "SlowSession":
                self.session = await self.context.__aenter__()
                return self

            async def __aexit__(self, *args: object) -> object:
                return await self.context.__aexit__(*args)

            def __getattr__(self, name: str) -> Any:
                return getattr(self.session, name)

            async def commit(self) -> None:
                await asyncio.sleep(1)
                await self.session.commit()

        bus = EventBus()
        persistence = PersistenceSubscriber(bus, SlowSession)
        await persistence.start()
        bus.publish(ToneDetected(uuid4(), "page", datetime.now(UTC), "radio"))
        await asyncio.sleep(0.05)
        started = time.perf_counter()
        await persistence.stop(timeout_s=0.2)
        elapsed = time.perf_counter() - started
        pending = [
            task.get_name()
            for task in asyncio.all_tasks()
            if not task.done() and task.get_name().startswith("tonewatch-")
        ]
        await engine.dispose()
        assert elapsed < 0.5
        assert pending == []

    asyncio.run(run())


def test_persistence_stop_propagates_caller_cancellation_and_abandons_commit(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'cancel.sqlite'}")
        await create_database_schema(engine)
        commit_started = asyncio.Event()
        release_commit = asyncio.Event()

        class SlowSession:
            def __init__(self) -> None:
                self.context = sessions()
                self.session: Any = None

            async def __aenter__(self) -> "SlowSession":
                self.session = await self.context.__aenter__()
                return self

            async def __aexit__(self, *args: object) -> object:
                return await self.context.__aexit__(*args)

            def __getattr__(self, name: str) -> Any:
                return getattr(self.session, name)

            async def commit(self) -> None:
                commit_started.set()
                await release_commit.wait()
                await self.session.commit()

        bus = EventBus()
        persistence = PersistenceSubscriber(bus, SlowSession)
        await persistence.start()
        bus.publish(ToneDetected(uuid4(), "page", datetime.now(UTC), "radio"))
        await asyncio.wait_for(commit_started.wait(), 1)

        stopper = asyncio.create_task(persistence.stop(timeout_s=10))
        await asyncio.sleep(0)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopper
        assert persistence._commit_task is None
        release_commit.set()
        await persistence.stop()
        await engine.dispose()

    asyncio.run(run())


def test_supervisor_admin_loop_uses_injected_sleep_and_evaluates_each_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        config = AppConfig()
        ticks = 0
        evaluated: list[dict[str, object]] = []

        async def fake_sleep(delay: float) -> None:
            nonlocal ticks
            assert delay == 30.0
            ticks += 1
            if ticks == 2:
                supervisor._stopping = True

        supervisor = Supervisor(config, EventBus(), None, sleep=fake_sleep)

        async def evaluate(snapshot: dict[str, object]) -> None:
            evaluated.append(snapshot)

        monkeypatch.setattr(supervisor.admin_alerts, "evaluate", evaluate)
        await supervisor._admin_loop()
        assert len(evaluated) == 2

    asyncio.run(run())


def test_supervisor_reports_absent_channel_and_diagnostics() -> None:
    supervisor = Supervisor(AppConfig(), EventBus(), None)
    assert supervisor.channel_for("missing") is None
    assert supervisor.source_status("missing") == (None, None)
    assert supervisor.source_diagnostics("missing") is None


def test_persistence_edge_helpers_handle_missing_database_and_unsafe_file(tmp_path: Path) -> None:
    async def run() -> None:
        persistence = PersistenceSubscriber(EventBus(), None)
        await persistence._persist(object())
        assert persistence.recordings_root is None
        assert _relative_path(tmp_path, tmp_path.parent / "outside.mp3") == "outside.mp3"

    asyncio.run(run())


def test_channel_level_tap_and_candidate_clip_empty_window() -> None:
    async def run() -> None:
        channel = Channel(FileSource(id="radio", name="radio", path="x.wav"), [], EventBus())
        channel._anchor_wall = datetime.now(UTC)
        levels: list[float] = []
        channel.add_level_tap(levels.append)
        channel._publish_level(_frame("radio", 1), -20.0)
        channel.remove_level_tap(levels.append)
        assert levels == [-20.0]
        candidate = cast("Any", type("Candidate", (), {"start_s": 1, "end_s": 2})())
        assert channel._candidate_clip(candidate) is None

    asyncio.run(run())


def test_watchdog_clipping_marks_feed_unhealthy() -> None:
    async def run() -> None:
        now = [10.0]
        watchdog = Watchdog("radio", EventBus(), clock=lambda: now[0], clip_ratio=0.5)
        watchdog._clips = deque([(0.0, 1, 1)])
        watchdog.check()
        assert watchdog.healthy is False and watchdog._unhealthy_reason == "clipping"

    asyncio.run(run())


def test_supervisor_starts_and_stops_admin_timer_task() -> None:
    async def run() -> None:
        config = AppConfig(admin_alerts=AdminAlertsConfig(enabled=True))
        supervisor = Supervisor(config, EventBus(), None, sleep=lambda _: asyncio.sleep(0))
        await supervisor.start()
        assert supervisor._admin_task is not None
        await supervisor.stop()
        assert supervisor._admin_task is None

    asyncio.run(run())


def test_watchdog_conditions_and_hysteresis() -> None:
    async def run() -> None:
        now = [0.0]
        bus = EventBus()
        subscription = bus.subscribe(FeedHealthChanged)
        watchdog = Watchdog(
            "radio", bus, clock=lambda: now[0], no_data_s=10, flatline_s=5, recovery_s=2
        )
        watchdog.on_frame(_frame("radio", 0))
        now[0] = 11
        watchdog.check()
        await asyncio.sleep(0)
        event = subscription.queue.get_nowait()
        assert isinstance(event, FeedHealthChanged)
        assert event.healthy is False and event.reason == "no_data"
        watchdog.on_frame(AudioFrame(np.full(1600, 0.1, dtype=np.float32), 11, "radio"))
        await asyncio.sleep(0)
        assert subscription.queue.empty()
        now[0] = 13
        watchdog.check()
        await asyncio.sleep(0)
        event = subscription.queue.get_nowait()
        assert isinstance(event, FeedHealthChanged) and event.healthy is True

    asyncio.run(run())


def test_watchdog_flatline_clipping_disconnect_and_recovery() -> None:
    async def run() -> None:
        now = [0.0]
        bus = EventBus()
        subscription = bus.subscribe(FeedHealthChanged)
        watchdog = Watchdog(
            "radio", bus, clock=lambda: now[0], flatline_s=5, clip_ratio=0.05, recovery_s=0
        )
        low = _frame("radio", 0)
        for offset in (0, 3, 6):
            now[0] = offset
            watchdog.on_frame(low)
            watchdog.check()
        await asyncio.sleep(0)
        assert any(event.reason == "flatline" for event in _drain(subscription))
        clipping_watchdog = Watchdog(
            "radio", bus, clock=lambda: now[0], clip_ratio=0.05, recovery_s=0
        )
        now[0] = 7
        clipping_watchdog.on_frame(AudioFrame(np.ones(1600, dtype=np.float32), 7, "radio"))
        await asyncio.sleep(0)
        assert any(event.reason == "clipping" for event in _drain(subscription))
        disconnect_watchdog = Watchdog("radio", bus, clock=lambda: now[0], recovery_s=0)
        now[0] = 8
        disconnect_watchdog.on_frame(_frame("radio", 8, discontinuity=True))
        await asyncio.sleep(0)
        assert any(event.reason == "disconnect" for event in _drain(subscription))
        disconnect_watchdog.on_error(SourceUnavailable("gone"))
        await asyncio.sleep(0)
        assert subscription.queue.empty()

    asyncio.run(run())


def test_watchdog_squelch_inputs_keep_off_and_rtl_silence_distinct() -> None:
    async def run() -> None:
        now = [0.0]
        bus = EventBus()
        subscription = bus.subscribe(FeedHealthChanged)
        watchdog = Watchdog("radio", bus, clock=lambda: now[0], flatline_s=5)
        watchdog.set_squelch_open(None)
        for offset in (0, 3, 6):
            now[0] = offset
            watchdog.on_frame(_frame("radio", offset))
            watchdog.check()
        await asyncio.sleep(0)
        assert any(event.reason == "flatline" for event in _drain(subscription))

        rtl = Watchdog("radio", bus, clock=lambda: now[0], flatline_s=5)
        rtl.set_rtl_squelch(True)
        for offset in (0, 3, 6):
            now[0] = offset
            rtl.on_frame(_frame("radio", offset))
            rtl.check()
        await asyncio.sleep(0)
        assert not any(event.reason == "flatline" for event in _drain(subscription))

    asyncio.run(run())


def test_watchdog_polling_uses_injected_sleep_and_exposes_state() -> None:
    async def run() -> None:
        bus = EventBus()
        watchdog = Watchdog("radio", bus, clock=lambda: 0.0)
        assert watchdog.healthy

        async def stop(_: float) -> None:
            await watchdog.stop()

        watchdog.sleep = stop
        await watchdog.run()

    asyncio.run(run())


def _drain(subscription: Any) -> list[FeedHealthChanged]:
    result: list[FeedHealthChanged] = []
    while not subscription.queue.empty():
        event = subscription.queue.get_nowait()
        if isinstance(event, FeedHealthChanged):
            result.append(event)
    return result


def test_storage_migration_helper_and_call_id_are_available(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
        await create_database_schema(engine)
        del sessions
        await engine.dispose()

    asyncio.run(run())
