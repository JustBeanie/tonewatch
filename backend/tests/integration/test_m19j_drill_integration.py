"""M19.4 behavioural integration tests through the real supervisor."""

from __future__ import annotations

import asyncio
import wave
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import numpy as np
import pytest
from sqlalchemy import select

from tonewatch.api.app import create_app
from tonewatch.config.models import AppConfig, FileSource, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.config.store import ConfigStore
from tonewatch.events import RecordingReady, ToneDetected
from tonewatch.settings import Settings
from tonewatch.storage.models import AuditEvent, Call, Recording

if TYPE_CHECKING:
    from pathlib import Path


def _write_silence(path: Path, seconds: float = 8) -> None:
    samples = np.zeros(round(seconds * 16_000), dtype="<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())


@pytest.mark.asyncio
async def test_drill_real_supervisor_persists_one_marked_call_and_recording(tmp_path: Path) -> None:
    wav = tmp_path / "silence.wav"
    _write_silence(wav)
    config = AppConfig(
        sources=[
            FileSource(
                id="radio",
                name="Radio",
                path=str(wav),
                realtime=True,
                loop=True,
            ),
            FileSource(id="other", name="Other", path=str(wav), realtime=True, loop=True),
        ],
        tone_sets=[
            ToneSet(
                id="page",
                name="Page",
                sequence=[
                    ToneSpec(freq_hz=1000, min_s=0.15, max_s=0.9),
                    ToneSpec(freq_hz=1200, min_s=0.15, max_s=0.9),
                ],
                record=RecordingPolicy(pre_roll_s=0, post_s=0.3, silence_stop_s=0.3, max_s=5),
            )
        ],
    )
    ConfigStore(tmp_path).save(config)
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False))
    async with app.router.lifespan_context(app):
        events = app.state.bus.subscribe()
        token = (tmp_path / "api_token").read_text(encoding="ascii").strip()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/admin/drill",
                headers={"Authorization": f"Bearer {token}"},
                json={"source_id": "radio", "toneset_id": "page", "voice_s": 0, "keep": True},
            )
            assert response.status_code == 202
            assert response.json()["expected_duration_s"] >= 0.9

        seen: list[object] = []
        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            event = await asyncio.wait_for(events.queue.get(), timeout=2)
            seen.append(event)
            if isinstance(event, RecordingReady):
                break
        detected = [event for event in seen if isinstance(event, ToneDetected)]
        ready = [event for event in seen if isinstance(event, RecordingReady)]
        assert detected and all(event.test and event.drill for event in detected)
        assert len(ready) == 1 and ready[0].test and ready[0].drill

        calls: list[Call] = []
        recordings: list[Recording] = []
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            async with app.state.session_factory() as session:
                calls = list((await session.scalars(select(Call))).all())
                recordings = list((await session.scalars(select(Recording))).all())
            if recordings:
                break
            await asyncio.sleep(0.05)
        assert len(calls) == 1 and calls[0].drill
        assert len(recordings) == 1

        # A normal event after the drill is not allowed to inherit drill state.
        normal = ToneDetected(calls[0].id, "page", calls[0].started_at, "radio")
        assert not normal.test and not normal.drill


class _FakeDrillChannel:
    def __init__(self) -> None:
        self.active = False

    @property
    def drill_active(self) -> bool:
        return self.active

    async def start_drill(self, _samples, _mode, _keep=False):
        self.active = True
        return uuid4(), 1.0


class _FakeDrillSupervisor:
    def __init__(self) -> None:
        self.channel = _FakeDrillChannel()
        self.running = True

    def channel_for(self, source_id: str):
        return self.channel if source_id in {"radio", "other"} and self.running else None

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return


@pytest.mark.asyncio
async def test_drill_api_safety_auth_ingress_resources_rate_limit_and_audit(tmp_path: Path) -> None:
    config = AppConfig(
        sources=[
            FileSource(id="radio", name="Radio", path="unused.wav"),
            FileSource(id="other", name="Other", path="unused.wav"),
            FileSource(id="disabled", name="Disabled", path="unused.wav", enabled=False),
        ],
        tone_sets=[
            ToneSet(id="page", name="Page", sequence=[ToneSpec(freq_hz=1000, min_s=0.1)]),
            ToneSet(
                id="off", name="Off", sequence=[ToneSpec(freq_hz=1200, min_s=0.1)], enabled=False
            ),
        ],
    )
    ConfigStore(tmp_path).save(config)
    supervisor = _FakeDrillSupervisor()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            recordings_root=tmp_path,
            addon_mode=True,
            zeroconf_enabled=False,
            ui_password="secret",  # noqa: S106 -- test-only credential for CSRF coverage.
        ),
        supervisor=supervisor,
    )
    async with app.router.lifespan_context(app):
        token = (tmp_path / "api_token").read_text(encoding="ascii").strip()
        bearer = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("172.30.32.2", 1234)),
            base_url="http://test",
        ) as client:
            body = {"source_id": "radio", "toneset_id": "page", "voice_s": 0}
            assert (await client.post("/api/admin/drill", json=body)).status_code == 401
            login = await client.post("/api/auth/login", json={"password": "secret"})
            assert login.status_code == 200
            assert (await client.post("/api/admin/drill", json=body)).status_code == 403
            assert (
                await client.post(
                    "/api/admin/drill",
                    json=body,
                    headers={"X-Ingress-Path": "/api/hassio_ingress/x"},
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/api/admin/drill",
                    json={**body, "source_id": "missing"},
                    headers=bearer,
                )
            ).status_code == 404
            assert (
                await client.post(
                    "/api/admin/drill",
                    json={**body, "toneset_id": "missing"},
                    headers=bearer,
                )
            ).status_code == 404
            assert (
                await client.post(
                    "/api/admin/drill",
                    json={**body, "source_id": "disabled"},
                    headers=bearer,
                )
            ).status_code == 409
            assert (
                await client.post(
                    "/api/admin/drill",
                    json={**body, "toneset_id": "off"},
                    headers=bearer,
                )
            ).status_code == 409
            supervisor.running = False
            assert (
                await client.post("/api/admin/drill", json=body, headers=bearer)
            ).status_code == 409
            supervisor.running = True
            first = await client.post("/api/admin/drill", json=body, headers=bearer)
            assert first.status_code == 202
            assert (
                await client.post("/api/admin/drill", json=body, headers=bearer)
            ).status_code == 429
            assert supervisor.channel.active
            supervisor.channel.active = False
            assert (
                await client.post(
                    "/api/admin/drill",
                    json={**body, "source_id": "other"},
                    headers=bearer,
                )
            ).status_code == 429
            async with app.state.session_factory() as session:
                audits = list((await session.scalars(select(AuditEvent))).all())
            drill_audit = next(item for item in audits if item.event_type == "drill_started")
            assert drill_audit.actor == "bearer"
            assert drill_audit.details == {
                "source_id": "radio",
                "toneset_id": "page",
                "mode": "replace",
                "keep": False,
            }
