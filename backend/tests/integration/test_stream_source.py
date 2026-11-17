"""Real PyAV and localhost HTTP integration test for stream sources."""

import asyncio
import io
import ipaddress
import threading
import wave
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from typing import Any, cast

import av
import httpx
import numpy as np
import pytest

from tonewatch.alerts.urlsafety import ResolvedURL
from tonewatch.config.models import StreamSource
from tonewatch.sources import stream as stream_module
from tonewatch.sources.base import AudioFrame
from tonewatch.sources.stream import StreamAudioSource


def make_ogg() -> bytes:
    """Encode one second of a 1 kHz tone with PyAV."""
    samples = (0.25 * np.sin(2 * np.pi * 1000 * np.arange(16_000) / 16_000)).astype(np.float32)
    output = io.BytesIO()
    container = av.open(output, mode="w", format="ogg")
    stream = cast("Any", container.add_stream("libopus", rate=16_000))
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="flt", layout="mono")
    frame.sample_rate = 16_000
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


class DropThenServe(BaseHTTPRequestHandler):
    """Send a truncated first response, then complete responses."""

    payload = b""
    requests = 0

    def do_GET(self) -> None:
        type(self).requests += 1
        self.send_response(200)
        self.send_header("Content-Type", "audio/ogg")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        if self.headers.get("User-Agent") == "ToneWatch redirect probe":
            self.wfile.write(self.payload)
        elif type(self).requests == 2:
            self.wfile.write(self.payload[:10])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(self.payload)

    def log_message(self, format_string: str, *args: object) -> None:
        del format_string, args


def test_stream_real_pyav_http_reconnect(monkeypatch) -> None:
    payload = make_ogg()
    DropThenServe.payload = payload
    DropThenServe.requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), DropThenServe)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sleeps: list[float] = []

    async def skip_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def allow_test_loopback(*_args: Any, **_kwargs: Any) -> ResolvedURL:
        return ResolvedURL(
            httpx.URL(f"http://127.0.0.1:{server.server_port}/audio.ogg"),
            ipaddress.ip_address("127.0.0.1"),
        )

    monkeypatch.setattr("tonewatch.sources.stream.resolve_and_validate", allow_test_loopback)

    async def run() -> list[AudioFrame]:
        source = StreamAudioSource(
            StreamSource(
                id="http",
                name="http",
                url=cast("Any", f"http://127.0.0.1:{server.server_port}/audio.ogg"),
            ),
            sleep=skip_sleep,
            jitter=lambda: 0,
        )
        await source.open()
        frames: list[AudioFrame] = []
        async for frame in source:
            frames.append(frame)
            if frame.discontinuity and sum(item.samples.size for item in frames) >= 0.95 * 16_000:
                await source.close()
                break
        return frames

    try:
        frames = asyncio.run(asyncio.wait_for(run(), timeout=10))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert DropThenServe.requests >= 2
    assert sleeps
    assert any(frame.discontinuity for frame in frames)
    assert all(frame.samples.dtype == np.float32 and frame.samples.ndim == 1 for frame in frames)
    assert all(
        current.stream_time_s > previous.stream_time_s for previous, current in pairwise(frames)
    )
    assert sum(frame.samples.size for frame in frames) >= 0.95 * 16_000


@pytest.mark.asyncio
async def test_live_stream_yields_before_eof_and_does_not_read_ahead(monkeypatch) -> None:
    """Exercise PyAV against a stalled peer with a bounded cleanup deadline."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x01\x00" * (512 * 1024))
    payload = output.getvalue()
    release = threading.Event()
    stalled = threading.Event()

    class LiveWave(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.headers.get("User-Agent") == "ToneWatch redirect probe":
                return
            if self.path == "/stalled.wav":
                stalled.set()
                release.wait(timeout=8)
                return
            with suppress(OSError):
                self.wfile.write(payload[: 256 * 1024])
                self.wfile.flush()
                if release.wait(timeout=8):
                    self.wfile.write(payload[256 * 1024 :])

        def log_message(self, format_string: str, *args: object) -> None:
            del format_string, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), LiveWave)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/audio.wav"

    async def resolve(address: str, **_kwargs: Any) -> ResolvedURL:
        return ResolvedURL(httpx.URL(address), ipaddress.ip_address("127.0.0.1"))

    monkeypatch.setattr(stream_module, "resolve_and_validate", resolve)
    real_resample = stream_module.resample_audio
    decode_threads: list[threading.Thread] = []

    def resample(samples: np.ndarray, rate: int) -> np.ndarray:
        decode_threads.append(threading.current_thread())
        return real_resample(samples, rate)

    monkeypatch.setattr(stream_module, "resample_audio", resample)
    source = StreamAudioSource(StreamSource(id="live", name="Live", url=cast("Any", url)))
    frames = aiter(source)
    stalled_url = url.replace("/audio", "/stalled")
    stalled_source = StreamAudioSource(
        StreamSource(id="stalled", name="Stalled", url=cast("Any", stalled_url))
    )
    pending: asyncio.Future[AudioFrame] | None = None
    try:
        first = await asyncio.wait_for(anext(frames), timeout=3)
        assert first.stream_time_s == 0
        assert len(decode_threads) == 1
        second = await asyncio.wait_for(anext(frames), timeout=1)
        assert second.stream_time_s == pytest.approx(first.samples.size / 16_000)
        assert len(decode_threads) == 2
        assert decode_threads[0] is decode_threads[1]
        await asyncio.wait_for(source.close(), timeout=3)
        assert not decode_threads[0].is_alive()

        pending = asyncio.ensure_future(anext(aiter(stalled_source)))
        assert await asyncio.to_thread(stalled.wait, 3)
        await asyncio.wait_for(stalled_source.close(), timeout=4)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=1)
    finally:
        release.set()
        await source.close()
        await stalled_source.close()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(thread.join, 2)
