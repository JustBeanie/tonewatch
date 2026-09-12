"""Real PyAV and localhost HTTP integration test for stream sources."""

import asyncio
import io
import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from typing import Any, cast

import av
import httpx
import numpy as np

from tonewatch.alerts.urlsafety import ResolvedURL
from tonewatch.config.models import StreamSource
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
