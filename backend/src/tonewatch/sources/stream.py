"""Network audio source with reconnect backoff."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
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


def _decode_url(url: str) -> list[np.ndarray]:
    safe_url = httpx.URL(url)
    options = {
        "protocol_whitelist": FFMPEG_PROTOCOL_WHITELIST,
        "max_redirects": "0",
    }
    if safe_url.scheme in {"rtsp", "rtsps"}:
        options["rtsp_transport"] = "tcp"
    if safe_url.scheme == "https":
        options["tls_verify"] = "1"
        options["ca_file"] = certifi.where()
    chunks: list[np.ndarray] = []
    with av.open(str(safe_url), options=options) as container:
        audio = next((stream for stream in container.streams if stream.type == "audio"), None)
        if audio is None:
            raise SourceUnavailable(f"stream contains no audio: {url}")
        for decoded in container.decode(audio):
            frame = cast("Any", decoded)
            array = cast("np.ndarray", frame.to_ndarray())
            rate = frame.sample_rate or cast("Any", audio).rate or 16_000
            chunks.append(
                resample_audio(
                    array.T if array.ndim == 2 and array.shape[0] < array.shape[1] else array, rate
                )
            )
    return chunks


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

    async def open(self) -> None:
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
        self._validated_url = resolved.original
        self._closed = False
        if not self._started:
            self._position = 0
            self._reconnected = False
            self._started = True

    async def close(self) -> None:
        self._closed = True
        self._validated_url = None

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
                    await self.open()
                chunks = await asyncio.to_thread(_decode_url, str(self._validated_url))
                for samples in chunks:
                    if self._closed:
                        return
                    yield AudioFrame(
                        samples, self._position / 16_000, self.config.id, self._reconnected
                    )
                    self._position += samples.size
                    self._reconnected = False
                if chunks:
                    self._reconnected = True
                delay = 1.0
            except SourceConfigError:
                raise
            except Exception as exc:
                self._reconnected = True
                self._validated_url = None
                await self._sleep(min(60.0, delay) * (0.5 + self._jitter()))
                delay = min(60.0, delay * 2)
                if self._closed:
                    return
                if not isinstance(exc, SourceUnavailable):
                    continue


StreamSource = StreamAudioSource
