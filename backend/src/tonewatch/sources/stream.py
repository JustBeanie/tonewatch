"""Network audio source with reconnect backoff."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from urllib.parse import urljoin

import av
import certifi
import httpx
import numpy as np

from tonewatch.alerts.urlsafety import ALLOWED_STREAM_SCHEMES, UnsafeURL, resolve_and_validate
from tonewatch.config.models import StreamSource as StreamConfig
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable
from tonewatch.sources.resample import resample_audio

FFMPEG_PROTOCOL_WHITELIST = "http,https,tcp,tls,rtsp,rtp,udp"
MAX_STREAM_REDIRECTS = 5
STREAM_IO_TIMEOUT_US = "2000000"


def _decode_url(url: str) -> Generator[np.ndarray]:
    safe_url = httpx.URL(url)
    options = {
        "protocol_whitelist": FFMPEG_PROTOCOL_WHITELIST,
        "max_redirects": "0",
        "rw_timeout": STREAM_IO_TIMEOUT_US,
    }
    if safe_url.scheme in {"rtsp", "rtsps"}:
        options["rtsp_transport"] = "tcp"
        options["timeout"] = STREAM_IO_TIMEOUT_US
    if safe_url.scheme == "https":
        options["tls_verify"] = "1"
        options["ca_file"] = certifi.where()

    def frames() -> Generator[np.ndarray | None]:
        with av.open(str(safe_url), options=options) as container:
            audio = next((stream for stream in container.streams if stream.type == "audio"), None)
            if audio is None:
                raise SourceUnavailable(f"stream contains no audio: {url}")
            yield None
            for decoded in container.decode(audio):
                frame = cast("Any", decoded)
                array = cast("np.ndarray", frame.to_ndarray())
                rate = frame.sample_rate or cast("Any", audio).rate or 16_000
                yield resample_audio(
                    array.T if array.ndim == 2 and array.shape[0] < array.shape[1] else array, rate
                )

    decoded = frames()
    # Open and validate the input eagerly. The generator owns the open container from here on.
    next(decoded)
    return cast("Generator[np.ndarray]", decoded)


class _Decoder:
    """Own the PyAV iterator and run each operation on the same worker."""

    def __init__(self, url: httpx.URL) -> None:
        self.url = url
        self.frames: Generator[np.ndarray] | None = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tonewatch-stream")
        self.closing: asyncio.Task[None] | None = None

    async def read(self) -> np.ndarray | None:
        return await asyncio.get_running_loop().run_in_executor(self.executor, self._read)

    def _read(self) -> np.ndarray | None:
        if self.frames is None:
            self.frames = _decode_url(str(self.url))
        return next(self.frames, None)

    def _close_frames(self) -> None:
        if self.frames is not None:
            self.frames.close()
            self.frames = None

    async def close(self) -> None:
        if self.closing is None:
            self.closing = asyncio.create_task(self._close())
        await asyncio.shield(self.closing)

    async def _close(self) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(self.executor, self._close_frames)
        finally:
            await asyncio.to_thread(self.executor.shutdown, wait=True)


async def _resolve_redirects(
    resolved: Any,
    *,
    allow_private: bool,
) -> Any:
    """Resolve and validate HTTP redirects before FFmpeg sees the URL."""
    current = resolved
    if current.original.scheme not in {"http", "https"}:
        return current
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=5.0,
            trust_env=False,
        ) as client:
            for hop in range(MAX_STREAM_REDIRECTS + 1):
                async with client.stream(
                    "GET",
                    str(current.original),
                    headers={"User-Agent": "ToneWatch redirect probe"},
                ) as response:
                    if not response.is_redirect:
                        return current
                    location = response.headers.get("location")
                if not location or hop == MAX_STREAM_REDIRECTS:
                    raise SourceUnavailable("stream redirect refused or limit exceeded")
                next_url = httpx.URL(urljoin(str(current.original), location))
                try:
                    current = await resolve_and_validate(
                        next_url,
                        schemes=ALLOWED_STREAM_SCHEMES,
                        allow_private=allow_private,
                    )
                except UnsafeURL as exc:
                    raise SourceConfigError(f"unsafe stream redirect: {exc}") from exc
    except SourceConfigError:
        raise
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"stream redirect probe failed: {exc}") from exc
    raise SourceUnavailable("stream redirect limit exceeded")


class StreamAudioSource:
    """Decode HTTP, Icecast, or RTSP audio without blocking the event loop."""

    def __init__(
        self,
        config: StreamConfig,
        *,
        settings: Any = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.config, self.settings, self._sleep, self._jitter = config, settings, sleep, jitter
        self._closed = False
        self._position = 0
        self._reconnected = False
        self._validated_url: httpx.URL | None = None
        self._started = False
        self._decoder: _Decoder | None = None
        self._retry: asyncio.Future[None] | None = None

    async def _resolve_url(self) -> httpx.URL:
        try:
            resolved = await resolve_and_validate(
                str(self.config.url),
                schemes=ALLOWED_STREAM_SCHEMES,
                allow_private=not bool(getattr(self.settings, "stream_block_private", False)),
            )
        except UnsafeURL as exc:
            raise SourceConfigError(f"unsafe stream URL: {exc}") from exc
        resolved = await _resolve_redirects(
            resolved,
            allow_private=not bool(getattr(self.settings, "stream_block_private", False)),
        )
        return cast("httpx.URL", resolved.original)

    async def open(self) -> None:
        self._validated_url = await self._resolve_url()
        self._closed = False
        if not self._started:
            self._position = 0
            self._reconnected = False
            self._started = True

    async def close(self) -> None:
        self._closed = True
        self._validated_url = None
        if self._retry is not None:
            self._retry.cancel()
        if self._decoder is not None:
            await self._decoder.close()

    async def __aenter__(self) -> StreamAudioSource:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[AudioFrame]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AudioFrame]:
        delay = 1.0
        while not self._closed:
            try:
                if self._validated_url is None:
                    self._validated_url = await self._resolve_url()
                if self._closed:
                    return
                decoder = self._decoder = _Decoder(self._validated_url)
                try:
                    while not self._closed:
                        samples = await decoder.read()
                        if samples is None or self._closed:
                            break
                        frame = AudioFrame(
                            samples, self._position / 16_000, self.config.id, self._reconnected
                        )
                        self._position += samples.size
                        self._reconnected = False
                        delay = 1.0
                        yield frame
                finally:
                    await decoder.close()
                    self._decoder = None
            except SourceConfigError:
                raise
            except (SourceUnavailable, av.error.FFmpegError, OSError):
                pass
            if self._closed:
                return
            self._reconnected = True
            self._validated_url = None
            self._retry = asyncio.ensure_future(self._sleep(delay * (0.5 + self._jitter())))
            try:
                await self._retry
            except asyncio.CancelledError:
                if not self._closed:
                    raise
            finally:
                self._retry = None
            delay = min(60.0, delay * 2)


StreamSource = StreamAudioSource
