"""M3 audio source contracts and deterministic behavior."""

import asyncio
import threading
import wave
from pathlib import Path
from typing import Any, cast

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from tonewatch.config.models import FileSource
from tonewatch.config.models import RtlSdrSource as RtlConfig
from tonewatch.config.models import SoundcardSource as SoundcardConfig
from tonewatch.config.models import StreamSource as StreamConfig
from tonewatch.events import EventBus, FeedHealthChanged
from tonewatch.sources.base import AudioFrame, SourceConfigError, make_source
from tonewatch.sources.file import FileAudioSource
from tonewatch.sources.resample import resample_audio
from tonewatch.sources.rtlsdr import RtlSdrSource
from tonewatch.sources.soundcard import SoundcardSource as SoundcardAudioSource
from tonewatch.sources.stream import StreamAudioSource


def config_file(path: str, *, realtime: bool = False, loop: bool = False) -> FileSource:
    return FileSource(id="file", name="file", path=path, realtime=realtime, loop=loop)


def write_wav(path: Path, samples: np.ndarray, rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        stereo = np.column_stack((samples, -samples))
        output.writeframes((stereo * 32767).astype("<i2").tobytes())


def test_frame_is_frozen_and_resampler_is_mono_16k() -> None:
    frame = AudioFrame(np.zeros(2, dtype=np.float32), 0, "x")
    assert frame.discontinuity is False
    tone = np.sin(2 * np.pi * 1000 * np.arange(8000) / 8000).astype(np.float32)
    result = resample_audio(np.column_stack((tone, tone)), 8000)
    assert result.dtype == np.float32
    assert result.shape == (16000,)
    spectrum = np.abs(np.fft.rfft(result))
    assert abs(np.argmax(spectrum) - 1000) <= 2


def test_file_fast_mode_timestamps_and_loop(tmp_path: Path) -> None:
    samples = np.linspace(-0.5, 0.5, 800, dtype=np.float32)
    path = tmp_path / "input.wav"
    write_wav(path, samples)

    async def run() -> list[AudioFrame]:
        source = FileAudioSource(config_file(str(path), loop=True), chunk_size=400)
        await source.open()
        frames = []
        async for frame in source:
            frames.append(frame)
            if len(frames) == 3:
                await source.close()
        return frames

    frames = asyncio.run(run())
    assert [frame.stream_time_s for frame in frames] == [0, 0.025, 0.05]
    assert all(frame.samples.dtype == np.float32 for frame in frames)


def test_file_loop_keeps_stream_time_monotonic_across_wraps(tmp_path: Path) -> None:
    """Looping must not rewind stream time: calls, cooldowns and post-roll run on it."""
    samples = np.linspace(-0.5, 0.5, 800, dtype=np.float32)
    path = tmp_path / "input.wav"
    write_wav(path, samples)

    async def run() -> list[AudioFrame]:
        source = FileAudioSource(config_file(str(path), loop=True), chunk_size=400)
        await source.open()
        frames = []
        async for frame in source:
            frames.append(frame)
            if len(frames) == 10:
                await source.close()
        return frames

    frames = asyncio.run(run())
    times = [frame.stream_time_s for frame in frames]
    # 800 samples at 8 kHz resample to 1600 at 16 kHz: four 400-sample chunks per pass.
    assert np.allclose(times, [index * 0.025 for index in range(10)])
    assert np.all(np.diff(times) > 0)


def test_file_loop_realtime_pacing_continues_after_first_pass(tmp_path: Path) -> None:
    """Every pass is paced; the second pass must not run unthrottled."""
    samples = np.linspace(-0.5, 0.5, 800, dtype=np.float32)
    path = tmp_path / "input.wav"
    write_wav(path, samples)
    now = [0.0]
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    async def run() -> None:
        source = FileAudioSource(
            config_file(str(path), realtime=True, loop=True),
            chunk_size=400,
            clock=lambda: now[0],
            sleep=sleep,
        )
        await source.open()
        count = 0
        async for _frame in source:
            count += 1
            if count == 10:
                await source.close()

    asyncio.run(run())
    # Frame k is due at k * 25 ms on a clock that only advances by sleeping, so every
    # frame after the first waits 25 ms, including those after the wrap at frame 4.
    assert delays[0] == 0
    assert all(abs(delay - 0.025) < 1e-9 for delay in delays[1:])
    assert abs(now[0] - 0.225) < 1e-9


@given(rate=st.sampled_from([8000, 22050, 44100, 48000]), channels=st.integers(1, 2))
def test_resampler_preserves_duration_and_frequency(rate: int, channels: int) -> None:
    count = rate // 2
    tone = np.sin(2 * np.pi * 1000 * np.arange(count) / rate).astype(np.float32)
    samples = np.column_stack([tone] * channels)
    result = resample_audio(samples, rate)
    assert abs(result.size / 16_000 - count / rate) <= 1 / 16_000
    peak = np.argmax(np.abs(np.fft.rfft(result[256:-256]))) * 16_000 / result[256:-256].size
    assert abs(peak - 1000) < 5


def test_file_realtime_uses_injected_clock_and_sleep(tmp_path: Path) -> None:
    path = tmp_path / "paced.wav"
    write_wav(path, np.ones(2400, dtype=np.float32), rate=16_000)
    now = [100.0]
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    async def run() -> list[AudioFrame]:
        source = FileAudioSource(
            config_file(str(path), realtime=True),
            chunk_size=800,
            clock=lambda: now[0],
            sleep=fake_sleep,
        )
        await source.open()
        return [frame async for frame in source]

    frames = asyncio.run(run())
    assert len(frames) == 3
    assert delays[0] == 0
    assert all(abs(delay - 0.05) < 1e-9 for delay in delays[1:])


def test_file_reader_supports_pcm_widths(tmp_path: Path) -> None:
    from tonewatch.sources.file import _decode_file

    for width, raw in (
        (1, bytes([128, 160, 96])),
        (3, b"\x00\x00\x00\x00\x00\x80"),
        (4, np.array([0, 1], dtype="<i4").tobytes()),
    ):
        path = tmp_path / f"pcm{width}.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(width)
            output.setframerate(16_000)
            output.writeframes(raw)
        decoded = _decode_file(path)
        assert decoded.dtype == np.float32
        assert decoded.size == len(raw) // width


def test_file_context_manager_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "context.wav"
    write_wav(path, np.ones(4, dtype=np.float32), rate=16_000)
    with np.testing.assert_raises(SourceConfigError):
        FileAudioSource(config_file(str(path)), chunk_size=0)

    async def run() -> None:
        source = FileAudioSource(config_file(str(path)), chunk_size=16)
        async with source:
            frame = await source.__aiter__().__anext__()
            assert frame.samples.size == 4

    asyncio.run(run())


def test_soundcard_filters_output_devices_and_selects_index(monkeypatch) -> None:
    from tonewatch.sources.soundcard import input_devices

    monkeypatch.setattr(
        "tonewatch.sources.soundcard.sd.query_devices",
        lambda: [
            {"name": "Output", "hostapi": 0, "max_input_channels": 0, "default_samplerate": 48000},
            {"name": "Input", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 48000},
        ],
    )
    monkeypatch.setattr("tonewatch.sources.soundcard.sd.query_hostapis", lambda: [{"name": "Host"}])
    assert [item["index"] for item in input_devices()] == [1]

    async def run() -> None:
        source = SoundcardAudioSource(SoundcardConfig(id="card", name="card", device=99))
        with np.testing.assert_raises(SourceConfigError):
            await source.open()

    asyncio.run(run())


def test_soundcard_callback_thread_and_oldest_drop(monkeypatch) -> None:
    devices = [
        {"name": "USB Radio", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 8000}
    ]
    monkeypatch.setattr("tonewatch.sources.soundcard.sd.query_devices", lambda: devices)
    monkeypatch.setattr("tonewatch.sources.soundcard.sd.query_hostapis", lambda: [{"name": "ALSA"}])

    class FakeStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    async def run() -> None:
        source = SoundcardAudioSource(
            SoundcardConfig(id="card", name="card", device="usb"),
            queue_size=1,
            stream_factory=FakeStream,
        )
        await source.open()

        def callback_twice() -> None:
            for _ in range(2):
                source._callback(np.ones((4, 2), dtype=np.float32), 4, None, None)

        thread = threading.Thread(target=callback_twice)
        thread.start()
        thread.join()
        await asyncio.sleep(0)
        assert source.dropped == 1
        await source.close()

    asyncio.run(run())


def test_event_bus_publish_from_thread() -> None:
    async def run() -> None:
        bus = EventBus()
        subscription = bus.subscribe(FeedHealthChanged)
        thread = threading.Thread(target=lambda: bus.publish(FeedHealthChanged("x", True)))
        thread.start()
        thread.join()
        await asyncio.sleep(0)
        event = await subscription.__anext__()
        assert isinstance(event, FeedHealthChanged)
        assert event.source_id == "x"

    asyncio.run(run())


def test_factory_and_file_error(tmp_path: Path) -> None:
    missing = FileAudioSource(config_file(str(tmp_path / "missing.wav")))
    with np.testing.assert_raises(SourceConfigError):
        asyncio.run(missing.open())
    assert cast("Any", make_source(config_file("x.wav"))).config.id == "file"
    assert (
        cast("Any", make_source(SoundcardConfig(id="card", name="card", device=0))).config.id
        == "card"
    )
    assert (
        cast(
            "Any",
            make_source(
                StreamConfig(id="stream", name="stream", url=cast("Any", "http://192.168.1.10/a"))
            ),
        ).config.id
        == "stream"
    )
    assert (
        cast("Any", make_source(RtlConfig(id="rtl", name="rtl", freq_hz=154000000))).config.id
        == "rtl"
    )


def test_stream_uses_thread_decode(monkeypatch) -> None:
    import tonewatch.sources.stream as stream_module

    monkeypatch.setattr(stream_module, "_decode_url", lambda _: [np.ones(4, dtype=np.float32)])

    async def skip_redirect_probe(resolved: Any, *, allow_private: bool) -> Any:
        del allow_private
        return resolved

    monkeypatch.setattr(stream_module, "_resolve_redirects", skip_redirect_probe)

    async def run() -> AudioFrame:
        source = StreamAudioSource(
            StreamConfig(id="stream", name="stream", url=cast("Any", "http://192.168.1.10/a"))
        )
        await source.open()
        iterator = source.__aiter__()
        frame = await iterator.__anext__()
        await source.close()
        return frame

    frame = asyncio.run(run())
    assert frame.stream_time_s == 0
    assert frame.discontinuity is False


def test_rtl_command_and_process_read(monkeypatch) -> None:
    config = RtlConfig(id="rtl", name="rtl", freq_hz=154000000, gain=12)
    source = RtlSdrSource(config, executable="python", sleep=lambda _: asyncio.sleep(0))
    assert source.argv()[0] == "python"
    assert "-M" in source.argv() and source.argv()[-1] == "-"
    monkeypatch.setattr("tonewatch.sources.rtlsdr.shutil.which", lambda _: "python")

    class Stdout:
        def __init__(self) -> None:
            self.done = False

        async def read(self, _: int) -> bytes:
            if self.done:
                return b""
            self.done = True
            return b"\x00\x40"

    class Process:
        def __init__(self) -> None:
            self.stdout = Stdout()
            self.returncode = 0

        async def wait(self) -> int:
            return 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

        def kill(self) -> None:
            self.returncode = -9

    async def create_process(*args: object, **kwargs: object) -> Process:
        del args, kwargs
        return Process()

    monkeypatch.setattr("tonewatch.sources.rtlsdr.asyncio.create_subprocess_exec", create_process)

    async def run() -> None:
        await source.open()
        frame = await source.__aiter__().__anext__()
        assert frame.samples.dtype == np.float32
        await source.close()

    asyncio.run(run())


def test_pyav_decode_helpers_and_stream_retry(monkeypatch) -> None:
    import tonewatch.sources.file as file_module
    import tonewatch.sources.stream as stream_module

    class Frame:
        sample_rate = 8000

        def to_ndarray(self) -> np.ndarray:
            return np.ones((1, 8), dtype=np.float32)

    class Stream:
        type = "audio"
        rate = 8000

    class Container:
        streams = [Stream()]

        def __enter__(self) -> "Container":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def decode(self, _: object) -> list[Frame]:
            return [Frame()]

    monkeypatch.setattr(file_module.av, "open", lambda *args, **kwargs: Container())
    assert file_module._decode_av(Path("audio.mp3")).size == 16
    monkeypatch.setattr(stream_module.av, "open", lambda *args, **kwargs: Container())
    assert stream_module._decode_url("http://localhost/audio")[0].size == 16

    attempts = 0

    def retry_decode(_: str) -> list[np.ndarray]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("offline")
        return [np.ones(4, dtype=np.float32)]

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(stream_module, "_decode_url", retry_decode)

    async def skip_redirect_probe(resolved: Any, *, allow_private: bool) -> Any:
        del allow_private
        return resolved

    monkeypatch.setattr(stream_module, "_resolve_redirects", skip_redirect_probe)

    async def run() -> AudioFrame:
        source = StreamAudioSource(
            StreamConfig(id="stream", name="stream", url=cast("Any", "http://192.168.1.10/a")),
            sleep=no_sleep,
            jitter=lambda: 0,
        )
        await source.open()
        frame = await source.__aiter__().__anext__()
        await source.close()
        return frame

    assert asyncio.run(run()).discontinuity is True


def test_soundcard_emits_selected_frame(monkeypatch) -> None:
    monkeypatch.setattr(
        "tonewatch.sources.soundcard.input_devices",
        lambda: [
            {
                "index": 2,
                "name": "Radio",
                "host_api": "X",
                "max_input_channels": 2,
                "default_rate": 16000,
            }
        ],
    )

    class Stream:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    async def run() -> AudioFrame:
        source = SoundcardAudioSource(
            SoundcardConfig(id="card", name="card", device="radio", channel="right"),
            stream_factory=Stream,
        )
        await source.open()
        source._enqueue(np.column_stack((np.zeros(8), np.ones(8))).astype(np.float32))
        frame = await source.__aiter__().__anext__()
        await source.close()
        return frame

    frame = asyncio.run(run())
    assert np.all(frame.samples == 1)
