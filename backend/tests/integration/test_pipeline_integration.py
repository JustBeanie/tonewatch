"""M3 pipeline integration through generated WAVs and SQLite persistence."""

import asyncio
import wave
from pathlib import Path

import numpy as np
from sqlalchemy import select

from tonewatch.config.models import AppConfig, FileSource, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.dsp.generator import concat, silence, tone
from tonewatch.events import EventBus
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.storage.db import create_database, upgrade_database
from tonewatch.storage.models import Call, CallToneSet


def _page(first: float, second: float) -> np.ndarray:
    return concat(tone(first, 0.35, 0.5), silence(0.1), tone(second, 0.35, 0.5))


def _write_wav(path: Path, signal: np.ndarray) -> None:
    pcm = np.clip(signal, -1, 1)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((pcm * 32767).astype("<i2").tobytes())


def test_two_file_channels_persist_stacked_and_separate_calls(tmp_path: Path) -> None:
    async def run() -> None:
        tone_a = ToneSet(
            id="a",
            name="A",
            sequence=[ToneSpec(freq_hz=700, min_s=0.2), ToneSpec(freq_hz=1200, min_s=0.2)],
            cooldown_s=0,
            record=RecordingPolicy(post_s=1),
        )
        tone_b = ToneSet(
            id="b",
            name="B",
            sequence=[ToneSpec(freq_hz=900, min_s=0.2), ToneSpec(freq_hz=1500, min_s=0.2)],
            cooldown_s=0,
            record=RecordingPolicy(post_s=1),
        )
        path_a = tmp_path / "a.wav"
        path_b = tmp_path / "b.wav"
        _write_wav(
            path_a,
            concat(silence(0.2), _page(700, 1200), silence(0.1), _page(900, 1500), silence(2)),
        )
        _write_wav(
            path_b,
            concat(silence(0.2), _page(700, 1200), silence(3), _page(700, 1200), silence(2)),
        )
        config = AppConfig(
            tone_sets=[tone_a, tone_b],
            sources=[
                FileSource(
                    id="source-a",
                    name="A",
                    path=str(path_a),
                    realtime=False,
                    tonesets=["a", "b"],
                ),
                FileSource(
                    id="source-b",
                    name="B",
                    path=str(path_b),
                    realtime=False,
                    tonesets=["a"],
                ),
            ],
        )
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'calls.sqlite'}")
        await upgrade_database(engine)
        supervisor = Supervisor(config, EventBus(), sessions)
        await supervisor.start()
        await supervisor.wait()
        await supervisor.persistence.drain()
        await supervisor.stop()
        async with sessions() as session:
            calls = (await session.scalars(select(Call).order_by(Call.started_at))).all()
            tones = (await session.scalars(select(CallToneSet))).all()
        by_source = {
            source: [call for call in calls if call.source_id == source]
            for source in ("source-a", "source-b")
        }
        assert len(by_source["source-a"]) == 1
        assert len(by_source["source-b"]) == 2
        tones_a = [
            tone_set for tone_set in tones if tone_set.call_id == by_source["source-a"][0].id
        ]
        assert {tone_set.toneset_id for tone_set in tones_a} == {"a", "b"}
        assert {call.source_id for call in calls} == {"source-a", "source-b"}
        assert all(call.status == "recorded" for call in calls)
        await engine.dispose()

    asyncio.run(run())
