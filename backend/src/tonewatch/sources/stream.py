"""Network audio source with reconnect backoff."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import av
import numpy as np

from tonewatch.config.models import StreamSource as StreamConfig
from tonewatch.sources.base import AudioFrame, SourceUnavailable
from tonewatch.sources.resample import resample_audio


def _decode_url(url: str) -> list[np.ndarray]:
    chunks: list[np.ndarray] = []
    with av.open(
        url, options={"rtsp_transport": "tcp"} if url.startswith("rtsp") else {}
    ) as container:
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


class StreamAudioSource:
    """Decode HTTP, Icecast, or RTSP audio without blocking the event loop."""

    def __init__(
        self,
        config: StreamConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.config, self._sleep, self._jitter = config, sleep, jitter
        self._closed = False
        self._position = 0
        self._reconnected = False

    async def open(self) -> None:
        self._closed = False
        self._position = 0
        self._reconnected = False

    async def close(self) -> None:
        self._closed = True

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
                chunks = await asyncio.to_thread(_decode_url, str(self.config.url))
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
            except Exception as exc:
                self._reconnected = True
                await self._sleep(min(60.0, delay) * (0.5 + self._jitter()))
                delay = min(60.0, delay * 2)
                if self._closed:
                    return
                if not isinstance(exc, SourceUnavailable):
                    continue


StreamSource = StreamAudioSource
