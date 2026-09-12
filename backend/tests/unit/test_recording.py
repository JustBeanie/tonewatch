"""M4 recording, encoding, and retention contract tests."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import av
import numpy as np
import pytest

from tonewatch.config.models import AppConfig, FileSource, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.segmenter import ToneSegment
from tonewatch.events import EventBus
from tonewatch.pipeline.channel import RecorderCall
from tonewatch.pipeline.ringbuffer import RingBuffer
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.recording.discovery import discovery_clip_path, encode_discovery_clip
from tonewatch.recording.encoder import AudioEncoder
from tonewatch.recording.recorder import CallRecorder
from tonewatch.recording.retention import RetentionPolicy, RetentionService
from tonewatch.sources.base import AudioFrame
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import DiscoveredTone, Recording


def toneset(*, formats: list[str] | None = None, max_s: float = 4) -> ToneSet:
    return ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
        record=RecordingPolicy(
            pre_roll_s=0.2,
            post_s=1,
            silence_stop_s=0.5,
            max_s=max_s,
            formats=cast("list[Literal['mp3', 'opus']]", formats or ["mp3"]),
        ),
    )


def test_encoder_writes_atomic_mp3_and_opus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replaced: list[tuple[str, str]] = []
    original = os.replace

    def replace(src: str, dst: str) -> None:
        replaced.append((src, dst))
        original(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    items = asyncio.run(
        AudioEncoder(tmp_path).encode(
            np.zeros(16_000, dtype=np.float32),
            call_id="abc",
            call_start=datetime(2026, 1, 2, tzinfo=UTC),
            formats={"mp3", "opus"},
            title="Page 2026",
            toneset_ids={"page"},
            source_id="radio",
        )
    )
    assert {item.format for item in items} == {"mp3", "opus"}
    assert all(item.path.parent == tmp_path / "2026" / "01" / "02" for item in items)
    assert all(item.duration_s == 1 for item in items)
    assert replaced and all(not Path(src).exists() for src, _ in replaced)
    with av.open(str(next(item.path for item in items if item.format == "mp3"))) as container:
        assert container.metadata["call_id"] == "abc"


def test_recorder_trims_guarded_tone_and_enforces_cap(tmp_path: Path) -> None:
    encoder = AudioEncoder(tmp_path)
    recorder = CallRecorder([toneset(max_s=1)], encoder)
    ring = RingBuffer(1, 16_000)
    call = RecorderCall(uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page"}))
    tone = ToneSegment(1000, 0.2, 0.4, 0.9, True)
    for at in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        frame = AudioFrame(np.full(1600, 0.1, dtype=np.float32), at, "radio")
        ring.extend(frame.samples, stream_time_s=at)
        output = EngineOutput((), (tone,), ()) if at == 0.2 else EngineOutput((), (), ())
        recorder.process(frame, ring, output, call)
    assert recorder.should_stop(1.1)
    trimmed = recorder._trim()
    assert trimmed.size < sum(item.size for item in recorder.samples)
    result = asyncio.run(recorder.finish())
    assert result is not None and result.files[0].path.exists()


def test_retention_deletes_oldest_and_refuses_escape(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    root.mkdir()
    inside = root / "2026" / "01" / "01"
    inside.mkdir(parents=True)
    first = inside / "first.mp3"
    first.write_bytes(b"1")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"2")

    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
        await create_database_schema(engine)
        async with sessions() as session:
            session.add(
                Recording(
                    call_id=uuid4(), format="mp3", path=str(first), duration_s=1, size_bytes=1
                )
            )
            await session.commit()
            await RetentionService(root, RetentionPolicy(max_total_bytes=0)).enforce(session)
        await engine.dispose()

    asyncio.run(run())
    assert not first.exists()

    async def escape() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'escape.sqlite'}")
        await create_database_schema(engine)
        async with sessions() as session:
            session.add(
                Recording(
                    call_id=uuid4(), format="mp3", path=str(outside), duration_s=1, size_bytes=2
                )
            )
            await session.commit()
            with pytest.raises(ValueError):
                await RetentionService(root, RetentionPolicy(max_total_bytes=0)).enforce(session)
        await engine.dispose()

    asyncio.run(escape())


def test_discovered_clips_follow_retention_and_safe_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recordings"
    clip = root / "discovered" / "1.mp3"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"clip")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside")

    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'discovery.sqlite'}")
        await create_database_schema(engine)
        async with sessions() as session:
            session.add_all(
                [
                    DiscoveredTone(
                        id=1,
                        mean_frequencies=[1000],
                        median_durations=[2],
                        count=1,
                        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        last_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        source_ids=["radio"],
                        status="new",
                        best_clip_recording_path=str(clip),
                    ),
                    DiscoveredTone(
                        id=2,
                        mean_frequencies=[1200],
                        median_durations=[2],
                        count=1,
                        first_seen=datetime(2026, 1, 2, tzinfo=UTC),
                        last_seen=datetime(2026, 1, 2, tzinfo=UTC),
                        source_ids=["radio"],
                        status="dismissed",
                    ),
                    DiscoveredTone(
                        id=3,
                        mean_frequencies=[1400],
                        median_durations=[2],
                        count=1,
                        first_seen=datetime(2026, 1, 3, tzinfo=UTC),
                        last_seen=datetime(2026, 1, 3, tzinfo=UTC),
                        source_ids=["radio"],
                        status="new",
                        best_clip_recording_path=str(outside),
                    ),
                ]
            )
            await session.commit()
            service = RetentionService(root, RetentionPolicy(max_total_bytes=0))
            assert clip in await service.enforce(session)
            assert not clip.exists() and outside.exists()
            assert len(await service.enforce_discovered(session, cap=0)) == 0
        await engine.dispose()

    asyncio.run(run())

    with pytest.raises(ValueError):
        discovery_clip_path(tmp_path, 0)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise OSError

    monkeypatch.setattr(AudioEncoder, "encode_samples_to_path", broken)
    with pytest.raises(OSError):
        encode_discovery_clip(
            root,
            4,
            np.zeros(1600, dtype=np.float32),
            call_start=datetime(2026, 1, 1, tzinfo=UTC),
            source_id="radio",
        )
    assert not list((root / "discovered").glob(".4.*.tmp"))


def test_recorder_policy_union_and_silence_stop(tmp_path: Path) -> None:
    other = toneset(formats=["opus"], max_s=8).model_copy(update={"id": "other"})
    recorder = CallRecorder([toneset(), other], AudioEncoder(tmp_path))
    ring = RingBuffer(1, 16_000)
    call = RecorderCall(
        uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page", "other"})
    )
    frame = AudioFrame(np.zeros(1600, dtype=np.float32), 0, "radio")
    ring.extend(frame.samples, stream_time_s=0)
    recorder.process(frame, ring, EngineOutput((), (), ()), call)
    assert recorder.max_s == 8 and recorder.formats == {"mp3", "opus"}
    assert recorder.should_stop(0.1, frame.samples) is False
    assert not recorder.should_stop(0.2, frame.samples)
    assert not recorder.should_stop(0.3, frame.samples)
    assert not recorder.should_stop(0.4, frame.samples)
    assert recorder.should_stop(0.6, frame.samples)


def test_recorder_empty_and_failed_encode(tmp_path: Path) -> None:
    assert asyncio.run(CallRecorder([], AudioEncoder(tmp_path)).finish()) is None

    class Broken:
        async def encode(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            raise OSError("broken")

    recorder = CallRecorder([toneset()], cast("AudioEncoder", Broken()))
    ring = RingBuffer(1, 16_000)
    frame = AudioFrame(np.zeros(1600, dtype=np.float32), 0, "radio")
    ring.extend(frame.samples, stream_time_s=0)
    recorder.process(
        frame,
        ring,
        EngineOutput((), (), ()),
        RecorderCall(uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page"})),
    )
    with pytest.raises(OSError):
        asyncio.run(recorder.finish())


def test_recorder_merges_policy_on_stack_and_handles_empty_policy(tmp_path: Path) -> None:
    recorder = CallRecorder(
        [toneset(), toneset(formats=["opus"], max_s=8).model_copy(update={"id": "other"})],
        AudioEncoder(tmp_path),
    )
    with pytest.raises(ValueError):
        recorder._policy(frozenset({"missing"}))
    ring = RingBuffer(1, 16_000)
    frame = AudioFrame(np.full(1600, 0.1, dtype=np.float32), 0, "radio")
    ring.extend(frame.samples, stream_time_s=0)
    first = RecorderCall(uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page"}))
    second = RecorderCall(first.id, "radio", first.started_at, frozenset({"page", "other"}))
    recorder.process(frame, ring, EngineOutput((), (), ()), first)
    recorder.process(frame, ring, EngineOutput((), (), ()), second)
    assert recorder.post_s == 1 and recorder.max_s == 8 and recorder.formats == {"mp3", "opus"}


def test_recorder_per_frame_cost_is_constant_after_call_start(tmp_path: Path) -> None:
    recorder = CallRecorder([toneset()], AudioEncoder(tmp_path))

    class CountingRing(RingBuffer):
        snapshots = 0

        def snapshot(self, seconds: float | None = None) -> np.ndarray:
            self.snapshots += 1
            return super().snapshot(seconds)

    ring = CountingRing(1, 16_000)
    first = RecorderCall(uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page"}))
    second = RecorderCall(first.id, "radio", first.started_at, frozenset({"page"}))
    for index in range(20):
        frame = AudioFrame(np.zeros(1600, dtype=np.float32), index / 10, "radio")
        ring.extend(frame.samples, stream_time_s=frame.stream_time_s)
        recorder.process(frame, ring, EngineOutput((), (), ()), first if index == 0 else second)
    assert ring.snapshots == 1


def test_channel_cancel_ends_task_during_finish() -> None:
    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowEncoder:
            async def encode(self, *args: Any, **kwargs: Any) -> list[Any]:
                del args, kwargs
                started.set()
                await release.wait()
                return []

        recorder = CallRecorder([toneset()], cast("AudioEncoder", SlowEncoder()))
        ring = RingBuffer(1, 16_000)
        frame = AudioFrame(np.zeros(1600, dtype=np.float32), 0, "radio")
        ring.extend(frame.samples, stream_time_s=0)
        recorder.process(
            frame,
            ring,
            EngineOutput((), (), ()),
            RecorderCall(uuid4(), "radio", datetime(2026, 1, 1, tzinfo=UTC), frozenset({"page"})),
        )
        task = asyncio.create_task(recorder.finish())
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert recorder.call is None

    asyncio.run(run())


def test_supervisor_starts_and_cancels_retention_task() -> None:
    class Service:
        async def enforce(self, session: object) -> list[Path]:
            del session
            return []

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

    async def sleep(_: float) -> None:
        await asyncio.Event().wait()

    async def run() -> None:
        class Channel:
            async def run(self) -> None:
                await asyncio.Event().wait()

        supervisor = Supervisor(
            toneset_config(),
            EventBus(),
            Session,
            sleep=sleep,
            retention_service=cast("RetentionService", Service()),
            channel_factory=cast("Any", Channel),
        )
        await supervisor.start()
        await supervisor.start()
        await asyncio.sleep(0)
        await supervisor.stop()

    asyncio.run(run())


def toneset_config() -> AppConfig:
    return AppConfig(sources=[FileSource(id="radio", name="radio", path="unused.wav")])
