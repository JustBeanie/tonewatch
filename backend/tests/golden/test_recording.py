"""M4 end-to-end recording goldens through Channel, PyAV, and SQLite."""

import asyncio
import wave
from pathlib import Path
from typing import cast

import av
import numpy as np
from sqlalchemy import select

from tonewatch.config.models import FileSource, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.generator import concat, silence, tone, voice_like
from tonewatch.dsp.spectrum import SpectrumAnalyzer
from tonewatch.events import EventBus
from tonewatch.pipeline.channel import Channel, RecorderCall
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.pipeline.ringbuffer import RingBuffer
from tonewatch.recording.encoder import AudioEncoder
from tonewatch.recording.recorder import CallRecorder
from tonewatch.sources.base import AudioFrame
from tonewatch.storage.db import create_database, upgrade_database
from tonewatch.storage.models import CallToneSet, Recording


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def _decode(path: Path) -> np.ndarray:
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = next(item for item in container.streams if item.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
        for frame in container.decode(stream):
            chunks.extend(
                converted.to_ndarray().reshape(-1).astype(np.float32) / 32768
                for converted in resampler.resample(cast("av.AudioFrame", frame))
            )
    return np.concatenate(chunks)


def _page(freq: float, duration: float = 0.4) -> np.ndarray:
    return tone(freq, duration, 0.5)


def _run_recording(
    tmp_path: Path,
    samples: np.ndarray,
    policy: RecordingPolicy,
    *,
    formats: list[str] | None = None,
    tone_configs: list[tuple[str, float]] | None = None,
) -> tuple[list[Path], list[CallToneSet]]:
    async def run() -> tuple[list[Path], list[CallToneSet]]:
        source_path = tmp_path / "input.wav"
        _write_wav(source_path, samples)
        tone_sets = [
            ToneSet(
                id=identifier,
                name=identifier,
                sequence=[ToneSpec(freq_hz=freq, min_s=0.2)],
                cooldown_s=0,
                record=policy.model_copy(update={"formats": formats or policy.formats}),
            )
            for identifier, freq in (tone_configs or [("page", 1000)])
        ]
        config = FileSource(id="radio", name="Radio", path=str(source_path), realtime=False)
        bus = EventBus()
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'calls.sqlite'}")
        await upgrade_database(engine)
        persistence = PersistenceSubscriber(bus, sessions)
        await persistence.start()
        recorder = CallRecorder(tone_sets, AudioEncoder(tmp_path / "recordings"), bus=bus)

        class Hook:
            def __call__(
                self,
                frame: AudioFrame,
                ring: RingBuffer,
                output: EngineOutput,
                call: RecorderCall | None,
                lifecycle: str,
            ) -> None:
                recorder.process(frame, ring, output, call, lifecycle)

            def should_stop(self, end_s: float, frame: np.ndarray) -> bool:
                return recorder.should_stop(end_s, frame)

            async def finish(self) -> None:
                await recorder.finish()

        channel = Channel(config, tone_sets, bus, recorder_hook=Hook())
        await channel.run()
        await recorder.finish()
        await persistence.drain()
        await persistence.stop()
        async with sessions() as session:
            paths = [Path(row.path) for row in (await session.scalars(select(Recording))).all()]
            tone_rows = list((await session.scalars(select(CallToneSet))).all())
        await engine.dispose()
        return paths, tone_rows

    return asyncio.run(run())


def _assert_no_tone(samples: np.ndarray, freq: float) -> None:
    analyzer = SpectrumAnalyzer()
    frames = analyzer.feed(samples)
    assert not any(
        frame.purity >= 0.6 and abs(frame.freq_hz - freq) <= freq * 0.02 for frame in frames
    )


def test_single_page_then_voice_duration_and_trim(tmp_path: Path) -> None:
    pre, page, voice = 0.5, 0.4, 1.2
    samples = concat(silence(pre), _page(1000, page), voice_like(voice))
    paths, _ = _run_recording(tmp_path, samples, RecordingPolicy(pre_roll_s=0.3, post_s=2, max_s=5))
    decoded = _decode(paths[0])
    expected = 0.3 + voice
    assert abs(decoded.size / 16_000 - expected) <= 0.3
    _assert_no_tone(decoded, 1000)


def test_three_stacked_pages_are_one_trimmed_recording(tmp_path: Path) -> None:
    voice = 1.2
    samples = concat(
        silence(0.5),
        _page(1000),
        silence(0.15),
        _page(1200),
        silence(0.15),
        _page(1400),
        voice_like(voice),
    )
    paths, tone_rows = _run_recording(
        tmp_path,
        samples,
        RecordingPolicy(pre_roll_s=0.3, post_s=2, max_s=8),
        tone_configs=[("a", 1000), ("b", 1200), ("c", 1400)],
    )
    assert len(paths) == 1 and len(tone_rows) == 3
    decoded = _decode(paths[0])
    assert abs(decoded.size / 16_000 - (0.3 + voice)) <= 0.3
    for frequency in (1000, 1200, 1400):
        _assert_no_tone(decoded, frequency)


def test_silence_early_stop(tmp_path: Path) -> None:
    last_voice, stop = 1.0, 0.6
    samples = concat(silence(0.5), _page(1000), voice_like(last_voice), silence(2))
    paths, _ = _run_recording(
        tmp_path, samples, RecordingPolicy(pre_roll_s=0.3, post_s=5, silence_stop_s=stop, max_s=8)
    )
    duration = _decode(paths[0]).size / 16_000
    expected = 0.3 + last_voice + stop
    assert abs(duration - expected) <= 0.3


def test_max_cap(tmp_path: Path) -> None:
    cap = 2.0
    samples = concat(silence(0.5), _page(1000), voice_like(5))
    paths, _ = _run_recording(
        tmp_path, samples, RecordingPolicy(pre_roll_s=0.3, post_s=5, max_s=cap)
    )
    assert abs(_decode(paths[0]).size / 16_000 - cap) <= 0.1


def test_mp3_and_opus_have_equal_decoded_duration(tmp_path: Path) -> None:
    samples = concat(silence(0.5), _page(1000), voice_like(1.2))
    paths, _ = _run_recording(
        tmp_path,
        samples,
        RecordingPolicy(pre_roll_s=0.3, post_s=2, max_s=5),
        formats=["mp3", "opus"],
    )
    assert {path.suffix for path in paths} == {".mp3", ".ogg"}
    durations = [_decode(path).size / 16_000 for path in paths]
    assert abs(durations[0] - durations[1]) <= 0.05
