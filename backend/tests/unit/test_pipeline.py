"""M3.6/M3.7 pipeline contract tests."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast
from uuid import uuid4

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select

from tonewatch.config.models import AppConfig, FileSource, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.matcher import Detection
from tonewatch.events import CallClosed, Event, EventBus, FeedHealthChanged, ToneDetected
from tonewatch.pipeline.channel import Channel, RecorderCall
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.pipeline.ringbuffer import RingBuffer
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.pipeline.watchdog import Watchdog
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import Call, CallToneSet


def _toneset(toneset_id: str, *, post_s: float = 3) -> ToneSet:
    return ToneSet(
        id=toneset_id,
        name=toneset_id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
        record=RecordingPolicy(post_s=post_s),
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
