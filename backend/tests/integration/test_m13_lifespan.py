"""M13 lifecycle integration through the real application composition root."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from sqlalchemy import select

from tonewatch.api.app import create_app
from tonewatch.config.models import AppConfig, FileSource, ToneSet
from tonewatch.config.store import ConfigStore
from tonewatch.dsp.generator import concat, silence, tone
from tonewatch.settings import Settings
from tonewatch.storage.models import CallToneSet, DiscoveredTone


def _write_wav(path: Path) -> None:
    samples = concat(tone(1000, 1, 0.5), silence(0.1), tone(1500, 1, 0.5), silence(1))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


async def _discovered(app: Any) -> list[DiscoveredTone]:
    async with app.state.session_factory() as session:
        result = await session.scalars(select(DiscoveredTone).order_by(DiscoveredTone.id))
        rows = list(result.all())
        result.close()
        return rows


async def _wait_for_discovered(app: Any) -> list[DiscoveredTone]:
    async with asyncio.timeout(10):
        while True:
            rows = await _discovered(app)
            if rows:
                return rows
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_discovery_lifespan_persists_promotes_and_replays(tmp_path: Path) -> None:
    source_path = tmp_path / "unknown.wav"
    _write_wav(source_path)
    settings = Settings(
        data_dir=tmp_path,
        recordings_root=tmp_path / "recordings",
        zeroconf_enabled=False,
    )
    ConfigStore(tmp_path).save(
        AppConfig(
            sources=[FileSource(id="radio", name="Radio", path=str(source_path), realtime=False)]
        )
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await app.state.supervisor.wait()
        await app.state.supervisor.persistence.drain()
        rows = await _wait_for_discovered(app)
        assert len(rows) == 1 and rows[0].status == "new"
        assert rows[0].best_clip_recording_path is not None
        assert await asyncio.to_thread(Path(rows[0].best_clip_recording_path).is_file)

        token = await asyncio.to_thread((tmp_path / "api_token").read_text, encoding="ascii")
        token = token.strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            draft_response = await client.post(
                f"/api/discovered-tones/{rows[0].id}/promote", headers=headers
            )
            assert draft_response.status_code == 200
            draft = draft_response.json()
            saved = await client.post(
                "/api/tonesets",
                headers={**headers, "Content-Type": "application/json"},
                json={**draft, "discovered_tone_id": rows[0].id},
            )
            assert saved.status_code == 201

        promoted = (await _discovered(app))[0]
        assert promoted.status == "promoted"
        tone_set = ToneSet.model_validate(draft)
        app.state.config = AppConfig(
            tone_sets=[tone_set],
            sources=[
                FileSource(id="radio-replay", name="Replay", path=str(source_path), realtime=False)
            ],
        )
        await app.state.supervisor.reload(app.state.config)
        await app.state.supervisor.wait()
        await app.state.supervisor.persistence.drain()
        async with app.state.session_factory() as session:
            detections = list((await session.scalars(select(CallToneSet))).all())
        assert any(item.toneset_id == tone_set.id for item in detections)
        assert len(await _discovered(app)) == 1
