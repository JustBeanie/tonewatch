"""W1a composition-root tests through the real application lifespan."""

import asyncio
import ipaddress
import json
import os
import wave
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import av
import httpx
import numpy as np
import pytest
from pydantic import AnyUrl
from sqlalchemy import select

from tonewatch.alerts import webhook
from tonewatch.alerts.urlsafety import ResolvedURL
from tonewatch.api.app import create_app
from tonewatch.config.models import (
    AppConfig,
    FileSource,
    RecordingPolicy,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.config.store import ConfigStore
from tonewatch.dsp.generator import concat, silence, tone, voice_like
from tonewatch.events import FeedHealthChanged
from tonewatch.recording.retention import RetentionPolicy
from tonewatch.settings import Settings
from tonewatch.sources.file import FileAudioSource
from tonewatch.storage.db import create_database, upgrade_database
from tonewatch.storage.models import AlertAttempt, Call, Recording


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def _page(first: float = 700, second: float = 1200) -> np.ndarray:
    return concat(tone(first, 0.35, 0.5), silence(0.1), tone(second, 0.35, 0.5))


def _tone_set(*, post_s: float = 1.5, alert_targets: list[str] | None = None) -> ToneSet:
    return ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=700, min_s=0.2), ToneSpec(freq_hz=1200, min_s=0.2)],
        cooldown_s=0,
        alert_targets=alert_targets or [],
        record=RecordingPolicy(
            pre_roll_s=0.3,
            post_s=post_s,
            silence_stop_s=8,
            max_s=12,
            formats=["mp3"],
        ),
    )


def _settings(root: Path, **kwargs: Any) -> Settings:
    return Settings(
        data_dir=root,
        recordings_root=root / "recordings",
        zeroconf_enabled=False,
        **kwargs,
    )


def _seed_config(root: Path, config: AppConfig) -> None:
    ConfigStore(root).save(config)


async def _is_file(path: Path) -> bool:
    return await asyncio.to_thread(path.is_file)


async def _rows(app: Any) -> tuple[list[Call], list[Recording]]:
    async with app.state.session_factory() as session:
        calls = list((await session.scalars(select(Call).order_by(Call.started_at))).all())
        recordings = list((await session.scalars(select(Recording).order_by(Recording.id))).all())
    return calls, recordings


@pytest.mark.asyncio
async def test_app_records_call_end_to_end(tmp_path: Path) -> None:
    source_path = tmp_path / "input.wav"
    _write_wav(source_path, concat(silence(0.5), _page(), voice_like(3)))
    tone_set = _tone_set(post_s=4)
    _seed_config(
        tmp_path,
        AppConfig(
            tone_sets=[tone_set],
            sources=[FileSource(id="radio", name="Radio", path=str(source_path), realtime=False)],
        ),
    )
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        await app.state.supervisor.wait()
        await app.state.supervisor.persistence.drain()
        calls, recordings = await _rows(app)
        assert len(calls) == 1 and len(recordings) == 1
        recording = recordings[0]
        recording_path = Path(recording.path)
        assert await _is_file(recording_path)
        with av.open(str(recording_path)) as container:
            stream = next(item for item in container.streams if item.type == "audio")
            assert stream.duration is not None and stream.time_base is not None
            duration = float(stream.duration * stream.time_base)
        assert abs(duration - 3.3) <= 0.5
        token = (tmp_path / "api_token").read_text(encoding="ascii").strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/recordings/{recording.id}", headers=headers)
            ranged = await client.get(
                f"/api/recordings/{recording.id}",
                headers={**headers, "Range": "bytes=0-99"},
            )
        assert response.status_code == 200 and response.headers["content-type"].startswith("audio/")
        assert ranged.status_code == 206 and len(ranged.content) == 100


@pytest.mark.asyncio
async def test_source_eof_during_post_roll_finalizes_recording(tmp_path: Path) -> None:
    source_path = tmp_path / "eof.wav"
    _write_wav(source_path, concat(silence(0.5), _page(), voice_like(1)))
    _seed_config(
        tmp_path,
        AppConfig(
            tone_sets=[_tone_set(post_s=4)],
            sources=[
                FileSource(
                    id="radio", name="Radio", path=str(source_path), realtime=False, loop=False
                )
            ],
        ),
    )
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        await app.state.supervisor.wait()
        await app.state.supervisor.persistence.drain()
        calls, recordings = await _rows(app)
    assert len(calls) == 1 and len(recordings) == 1
    assert await _is_file(Path(recordings[0].path))


@pytest.mark.asyncio
async def test_sequential_calls_on_one_channel_produce_two_recordings(tmp_path: Path) -> None:
    source_path = tmp_path / "sequential.wav"
    samples = concat(
        silence(0.3),
        _page(),
        voice_like(0.5),
        silence(4),
        _page(),
        voice_like(0.5),
    )
    _write_wav(source_path, samples)
    sequential_tone_set = ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=700, min_s=0.2)],
        cooldown_s=0,
        record=RecordingPolicy(
            pre_roll_s=0.3,
            post_s=1,
            silence_stop_s=8,
            max_s=12,
            formats=["mp3"],
        ),
    )
    _seed_config(
        tmp_path,
        AppConfig(
            tone_sets=[sequential_tone_set],
            sources=[FileSource(id="radio", name="Radio", path=str(source_path), realtime=False)],
        ),
    )
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        await app.state.supervisor.wait()
        await app.state.supervisor.persistence.drain()
        calls, recordings = await _rows(app)
    assert len(calls) == 2 and len(recordings) == 2
    assert len({recording.path for recording in recordings}) == 2
    assert all([await _is_file(Path(recording.path)) for recording in recordings])


@pytest.mark.asyncio
async def test_healthy_feed_stays_healthy_through_supervisor(tmp_path: Path) -> None:
    source_path = tmp_path / "health.wav"
    _write_wav(source_path, silence(0.2))
    _seed_config(
        tmp_path,
        AppConfig(
            sources=[
                FileSource(
                    id="radio", name="Radio", path=str(source_path), realtime=True, loop=True
                )
            ]
        ),
    )
    current = [0.0]
    allow_frames = [True]
    phase_reached = asyncio.Event()

    async def source_sleep(delay: float) -> None:
        if not allow_frames[0]:
            await asyncio.Event().wait()
        current[0] += max(delay, 0.1)
        if current[0] >= 20:
            phase_reached.set()
        await asyncio.sleep(0)

    async def supervisor_sleep(delay: float) -> None:
        if not allow_frames[0]:
            current[0] += delay
        await asyncio.sleep(0)

    def source_factory(config: FileSource) -> FileAudioSource:
        return FileAudioSource(
            config,
            clock=lambda: current[0],
            sleep=source_sleep,
        )

    app = create_app(
        _settings(tmp_path),
        clock=lambda: current[0],
        sleep=supervisor_sleep,
        source_factory=source_factory,
        watchdog_no_data_s=2,
    )
    async with app.router.lifespan_context(app):
        subscription = app.state.bus.subscribe(FeedHealthChanged)
        await asyncio.wait_for(phase_reached.wait(), 2)
        await asyncio.sleep(0)
        assert not any(
            isinstance(event, FeedHealthChanged) and not event.healthy
            for event in _drain(subscription)
        )
        allow_frames[0] = False
        unhealthy = None
        for _ in range(20):
            await asyncio.sleep(0)
            events = _drain(subscription)
            unhealthy = next(
                (
                    event
                    for event in events
                    if isinstance(event, FeedHealthChanged)
                    and not event.healthy
                    and event.reason == "no_data"
                ),
                None,
            )
            if unhealthy is not None:
                break
        assert unhealthy is not None


def _drain(subscription: Any) -> list[object]:
    events: list[object] = []
    while not subscription.queue.empty():
        events.append(subscription.queue.get_nowait())
    return events


@pytest.mark.asyncio
async def test_retention_runs_in_app_lifespan(tmp_path: Path) -> None:
    recordings_root = tmp_path / "recordings"
    old_path = recordings_root / "2020" / "01" / "01" / "old.mp3"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"old")
    old_timestamp = 1_577_836_800
    os.utime(old_path, (old_timestamp, old_timestamp))
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'tonewatch.db'}")
    await upgrade_database(engine)
    async with sessions() as session:
        session.add(
            Recording(call_id=uuid4(), format="mp3", path=str(old_path), duration_s=1, size_bytes=3)
        )
        await session.commit()
    await engine.dispose()
    _seed_config(tmp_path, AppConfig())
    app = create_app(
        _settings(
            tmp_path,
            retention=RetentionPolicy(max_age_days=1, max_total_bytes=None, max_count=None),
        )
    )
    async with app.router.lifespan_context(app):
        for _ in range(20):
            await asyncio.sleep(0)
            async with app.state.session_factory() as session:
                rows = list((await session.scalars(select(Recording))).all())
            if not rows:
                break
    assert rows == [] and not old_path.exists()


@pytest.mark.asyncio
async def test_webhook_alert_fires_for_real_recorded_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[dict[str, object]] = []

    async def receiver(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers = await reader.readuntil(b"\r\n\r\n")
        header_map = dict(
            line.split(b":", 1) for line in headers.split(b"\r\n")[1:] if b":" in line
        )
        length = int(header_map[b"Content-Length"])
        body = await reader.readexactly(length)
        received.append(cast("dict[str, object]", json.loads(body)))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(receiver, "127.0.0.1", 0)
    port = cast("tuple[str, int]", server.sockets[0].getsockname())[1]
    source_path = tmp_path / "alert.wav"
    _write_wav(source_path, concat(silence(0.5), _page(), voice_like(1)))
    target = WebhookTarget(
        id="hook",
        name="Hook",
        url=AnyUrl(f"http://127.0.0.1:{port}/events"),
        allow_insecure_http=True,
    )
    _seed_config(
        tmp_path,
        AppConfig(
            tone_sets=[_tone_set(post_s=2, alert_targets=["hook"])],
            sources=[FileSource(id="radio", name="Radio", path=str(source_path), realtime=False)],
            alert_targets=[target],
        ),
    )
    original_resolver = webhook.resolve_and_validate

    async def test_resolver(value: str | httpx.URL, **kwargs: Any) -> ResolvedURL:
        url = httpx.URL(value)
        if url.host == "127.0.0.1":
            return ResolvedURL(url, ipaddress.ip_address("127.0.0.1"))
        return await original_resolver(value, **kwargs)

    monkeypatch.setattr(webhook, "resolve_and_validate", test_resolver)
    app = create_app(_settings(tmp_path))
    try:
        async with app.router.lifespan_context(app):
            await app.state.supervisor.wait()
            await app.state.supervisor.persistence.drain()
            for _ in range(20):
                if any(item.get("phase") == "recording_ready" for item in received):
                    break
                await asyncio.sleep(0.01)
            token = (tmp_path / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            ready = next(item for item in received if item.get("phase") == "recording_ready")
            recording_url = cast("str", ready["recording_url"])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(recording_url, headers=headers)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("audio/")
            async with app.state.session_factory() as session:
                attempts = list((await session.scalars(select(AlertAttempt))).all())
    finally:
        server.close()
        await server.wait_closed()
    assert {item["phase"] for item in received} >= {"pre_alert", "recording_ready"}
    assert {attempt.phase for attempt in attempts} >= {"pre_alert", "recording_ready"}
