"""M19.4 drill contracts (tests are intentionally written before implementation)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from uuid import uuid4

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from pydantic import AnyUrl
from sqlalchemy import create_engine, text

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.meshtastic import render_message
from tonewatch.api.routes.admin import _release_drill
from tonewatch.config.models import (
    AlertTarget,
    AppConfig,
    FileSource,
    MeshtasticTarget,
    MqttTarget,
    RecordingPolicy,
    ScriptTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.matcher import Detection
from tonewatch.events import EventBus, RecordingReady, RecordingStored, ToneDetected
from tonewatch.pipeline.channel import Channel, RecorderCall
from tonewatch.pipeline.drill import build_waveform
from tonewatch.recording.retention import RetentionPolicy, RetentionService
from tonewatch.settings import Settings
from tonewatch.sources.base import AudioFrame
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import Call, Recording


def test_drill_waveform_uses_tone_bounds_and_optional_voice() -> None:
    waveform = build_waveform([(1000.0, 0.1, 0.1), (1200.0, 0.2, 0.2)], voice_s=0.25, seed=7)

    assert waveform.expected_duration_s == pytest.approx(0.55)
    assert waveform.samples.dtype == np.float32
    assert waveform.samples.size == 8800
    assert float(np.max(np.abs(waveform.samples))) <= 1.0


def test_drill_waveform_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="duration"):
        build_waveform([(1000.0, 0.2, 0.1)], voice_s=0)


def test_drill_duration_is_safely_inside_bounds() -> None:
    waveform = build_waveform([(1000.0, 0.2, 1.0)], voice_s=0)
    assert waveform.expected_duration_s == pytest.approx(0.6)


class _InfiniteSource:
    async def open(self) -> None:
        return

    async def close(self) -> None:
        return

    def __aiter__(self):
        return self

    async def __anext__(self):
        return AudioFrame(np.zeros(1600, dtype=np.float32), 0.0, "radio")


class _OneDetectionEngine:
    emitted = False

    def __init__(self, _tonesets) -> None:
        type(self).emitted = False

    def feed(self, _samples: np.ndarray) -> EngineOutput:
        if type(self).emitted:
            return EngineOutput((), (), ())
        type(self).emitted = True
        return EngineOutput((), (), (Detection("page", 0.2, (), True),))


class _SequenceSource:
    def __init__(self, samples: list[np.ndarray]) -> None:
        self.samples = samples

    async def open(self) -> None:
        return

    async def close(self) -> None:
        return

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for index, samples in enumerate(self.samples):
            yield AudioFrame(samples, index * samples.size / 16_000, "radio")


class _CaptureEngine:
    captured: ClassVar[list[np.ndarray]] = []

    def __init__(self, _tonesets) -> None:
        type(self).captured = []

    def feed(self, samples: np.ndarray) -> EngineOutput:
        type(self).captured.append(samples.copy())
        return EngineOutput((), (), ())


class _Recorder:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.calls: list[RecorderCall] = []

    async def __call__(self, _frame, _ring, _output, call, _lifecycle) -> None:
        if call is not None:
            self.calls.append(call)

    async def finish(self) -> None:
        call = self.calls[-1]
        self.bus.publish(
            RecordingReady(call.id, "recording.mp3", "mp3", call.source_id, call.drill, call.drill)
        )


@pytest.mark.asyncio
async def test_post_roll_events_keep_test_and_drill_markers() -> None:
    source_config = FileSource(id="radio", name="Radio", path="unused.wav")
    toneset = ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
        record=RecordingPolicy(post_s=3),
    )
    bus = EventBus()
    sub = bus.subscribe()
    recorder = _Recorder(bus)
    channel = Channel(
        source_config,
        [toneset],
        bus,
        recorder_hook=cast("Any", recorder),
        source_factory=cast("Any", lambda _config: _InfiniteSource()),
        engine_factory=_OneDetectionEngine,
    )
    waveform = build_waveform([(1000, 0.1, 0.8)], voice_s=0)
    await channel.start_drill(waveform.samples, "replace")
    task = __import__("asyncio").create_task(channel.run())
    for _ in range(20):
        if len(recorder.calls) >= 2:
            break
        await __import__("asyncio").sleep(0)
    task.cancel()
    await __import__("asyncio").gather(task, return_exceptions=True)
    events = []
    while not sub.queue.empty():
        events.append(sub.queue.get_nowait())
    detected = next(item for item in events if isinstance(item, ToneDetected))
    ready = next(item for item in events if isinstance(item, RecordingReady))
    assert detected.test and detected.drill
    assert ready.test and ready.drill
    assert recorder.calls[-1].drill


def test_replace_and_mix_injection_preserve_task_and_peak() -> None:
    config = FileSource(id="radio", name="Radio", path="unused.wav")
    channel = Channel(config, [], EventBus())
    original = np.full(1600, 0.9, dtype=np.float32)

    async def run() -> None:
        task = asyncio.current_task()
        await channel.start_drill(np.full(1600, 0.9, dtype=np.float32), "replace")
        replaced = channel._apply_drill(original)
        assert np.allclose(replaced, 0.9)
        assert channel._apply_drill(original) is original
        await channel.start_drill(np.full(1600, 0.9, dtype=np.float32), "mix")
        mixed = channel._apply_drill(original)
        assert np.max(np.abs(mixed)) <= 1.0
        assert task is asyncio.current_task()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_channel_frames_replace_mix_and_resume_without_restart() -> None:
    config = FileSource(id="radio", name="Radio", path="unused.wav")
    live = np.full(1600, 0.8, dtype=np.float32)
    source = _SequenceSource([live, live, live, live])
    channel = Channel(
        config,
        [],
        EventBus(),
        source_factory=cast("Any", lambda _config: source),
        engine_factory=_CaptureEngine,
    )
    task = __import__("asyncio").create_task(channel.run())
    await channel.start_drill(np.full(3200, 0.6, dtype=np.float32), "replace")
    await task
    assert len(_CaptureEngine.captured) == 4
    assert np.allclose(_CaptureEngine.captured[0], 0.6)
    assert np.allclose(_CaptureEngine.captured[1], 0.6)
    assert np.allclose(_CaptureEngine.captured[2], 0.8)
    assert np.allclose(_CaptureEngine.captured[3], 0.8)

    source = _SequenceSource([live, live, live, live])
    channel = Channel(
        config,
        [],
        EventBus(),
        source_factory=cast("Any", lambda _config: source),
        engine_factory=_CaptureEngine,
    )
    task = __import__("asyncio").create_task(channel.run())
    await channel.start_drill(np.full(3200, 0.8, dtype=np.float32), "mix")
    await task
    assert np.max(np.abs(_CaptureEngine.captured[0])) <= 1.0
    assert np.allclose(_CaptureEngine.captured[2], 0.8)


@pytest.mark.asyncio
async def test_drill_retention_counts_and_preserves_keep(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'tonewatch.db'}")
    await create_database_schema(engine)
    now = datetime(2026, 1, 2, tzinfo=UTC)
    old = now - timedelta(hours=25)
    drill_id, kept_id, normal_id = uuid4(), uuid4(), uuid4()
    drill_path = tmp_path / "drill.mp3"
    kept_path = tmp_path / "kept.mp3"
    normal_path = tmp_path / "normal.mp3"
    for path in (drill_path, kept_path, normal_path):
        path.write_bytes(b"x")
    async with sessions() as session:
        session.add_all(
            [
                Call(id=drill_id, source_id="radio", started_at=old, drill=True),
                Call(id=kept_id, source_id="radio", started_at=old, drill=True, drill_keep=True),
                Call(id=normal_id, source_id="radio", started_at=old),
                Recording(
                    call_id=drill_id, format="mp3", path=str(drill_path), duration_s=1, size_bytes=1
                ),
                Recording(
                    call_id=kept_id, format="mp3", path=str(kept_path), duration_s=1, size_bytes=1
                ),
                Recording(
                    call_id=normal_id,
                    format="mp3",
                    path=str(normal_path),
                    duration_s=1,
                    size_bytes=1,
                ),
            ]
        )
        await session.commit()

        def clock() -> float:
            return now.timestamp()

        service = RetentionService(
            tmp_path,
            RetentionPolicy(max_age_days=None, drill_retention_hours=24),
            clock=clock,
        )
        plan = await service.plan(session)
        assert plan.counts["drills"] == 1
        await service.apply(session, plan)
    async with sessions() as session:
        assert await session.get(Call, drill_id) is None
        assert await session.get(Call, kept_id) is not None
        assert await session.get(Call, normal_id) is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_drill_delivery_failure_does_not_update_admin_failure_counter(monkeypatch) -> None:
    target = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test/hook"))
    toneset = ToneSet(
        id="page", name="Page", sequence=[ToneSpec(freq_hz=1000, min_s=0.1)], alert_targets=["hook"]
    )
    dispatcher = AlertDispatcher(
        AppConfig(tone_sets=[toneset], alert_targets=[target]), EventBus(), settings=Settings()
    )

    async def fail(*_args, **_kwargs):
        return SimpleNamespace(ok=False, status_code=500, error="failed")

    monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", fail)
    await dispatcher.handle(
        ToneDetected(uuid4(), "page", datetime.now(UTC), "radio", True, None, True)
    )
    assert dispatcher.output_health["hook"].consecutive_failures == 0


@pytest.mark.asyncio
async def test_cancelled_drill_release_clears_active_source() -> None:
    supervisor = SimpleNamespace(_drill_active_sources={"radio"})
    task = __import__("asyncio").create_task(_release_drill(supervisor, "radio", 60))
    await __import__("asyncio").sleep(0)
    task.cancel()
    await __import__("asyncio").gather(task, return_exceptions=True)
    assert supervisor._drill_active_sources == set()


@pytest.mark.asyncio
async def test_every_alert_target_receives_both_drill_markers(monkeypatch) -> None:
    mesh_target = MeshtasticTarget(
        id="mesh",
        name="Mesh",
        host="127.0.0.1",
        gateway_node_id="!12345678",
        channel_index=1,
        phases=["pre_alert"],
        coalesce_s=0,
    )
    targets: list[AlertTarget] = [
        MqttTarget(id="mqtt", name="MQTT"),
        WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test/hook")),
        ScriptTarget(id="script", name="Script", executable="tonewatch-test", enabled=True),
        mesh_target,
    ]
    toneset = ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
        alert_targets=[item.id for item in targets],
    )
    dispatcher = AlertDispatcher(AppConfig(tone_sets=[toneset], alert_targets=targets), EventBus())
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_send(target, payload, **_kwargs):
        sent.append((target.id, payload))
        return SimpleNamespace(ok=True, status_code=200, error=None)

    monkeypatch.setattr(dispatcher, "_send", fake_send)
    call_id = uuid4()
    await dispatcher.handle(
        ToneDetected(call_id, "page", datetime.now(UTC), "radio", True, None, True)
    )
    await dispatcher.handle(RecordingStored(call_id, 1, "mp3", "radio", True, True))
    await asyncio.sleep(0)
    assert {target_id for target_id, _payload in sent} == {item.id for item in targets}
    assert all(payload["test"] is True and payload["drill"] is True for _id, payload in sent)
    mesh_text = render_message(mesh_target, sent[-1][1])
    assert (
        mesh_text.startswith("DRILL ") and len(mesh_text.encode("utf-8")) <= mesh_target.max_bytes
    )


def test_migration_0008_to_0009_defaults_existing_calls_to_not_drill(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "src" / "tonewatch" / "storage" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0008_recording_created_at")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO calls (id, started_at, source_id, status) "
                "VALUES (:id, :started_at, :source_id, :status)"
            ),
            {
                "id": str(uuid4()),
                "started_at": datetime.now(UTC).isoformat(),
                "source_id": "radio",
                "status": "active",
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT drill, drill_keep FROM calls")).one() == (0, 0)
    engine.dispose()
