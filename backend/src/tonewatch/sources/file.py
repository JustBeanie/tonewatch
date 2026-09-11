"""File-backed audio source."""

from __future__ import annotations

import asyncio
import time
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import av
import numpy as np

from tonewatch.config.models import FileSource as FileConfig
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable
from tonewatch.sources.resample import resample_audio


async def _read_file(path: Path) -> np.ndarray:
    return await asyncio.to_thread(_decode_file, path)


def _decode_file(path: Path) -> np.ndarray:
    try:
        with wave.open(str(path), "rb") as source:
            width, channels, rate = (
                source.getsampwidth(),
                source.getnchannels(),
                source.getframerate(),
            )
            raw = source.readframes(source.getnframes())
        if width == 1:
            values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
        elif width == 2:
            values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        elif width == 3:
            octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
            integers = (
                octets[:, 0].astype(np.int32)
                | (octets[:, 1].astype(np.int32) << 8)
                | (octets[:, 2].astype(np.int32) << 16)
            )
            values = ((integers ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
        elif width == 4:
            values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
        else:
            raise SourceConfigError(f"unsupported WAV sample width: {width}")
        return resample_audio(values.reshape(-1, channels), rate)
    except (wave.Error, OSError):
        try:
            return _decode_av(path)
        except Exception as av_exc:
            raise SourceUnavailable(f"could not decode audio file {path}") from av_exc


def _decode_av(path: Path) -> np.ndarray:
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        audio = next((stream for stream in container.streams if stream.type == "audio"), None)
        if audio is None:
            raise SourceConfigError(f"file contains no audio stream: {path}")
        for decoded in container.decode(audio):
            frame = cast("Any", decoded)
            array = cast("np.ndarray", frame.to_ndarray())
            rate = frame.sample_rate or cast("Any", audio).rate or 16_000
            chunks.append(
                resample_audio(
                    array.T if array.ndim == 2 and array.shape[0] < array.shape[1] else array, rate
                )
            )
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, dtype=np.float32)


class FileAudioSource:
    """Replay an audio file in fixed-size normalized chunks."""

    def __init__(
        self,
        config: FileConfig,
        *,
        chunk_size: int = 1600,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config, self.chunk_size, self._clock, self._sleep = config, chunk_size, clock, sleep
        if chunk_size <= 0:
            raise SourceConfigError("chunk_size must be positive")
        self._samples: np.ndarray | None = None
        self._closed = False

    async def open(self) -> None:
        if not Path(self.config.path).is_file():
            raise SourceConfigError(f"audio file does not exist: {self.config.path}")
        self._samples = await _read_file(Path(self.config.path))
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    async def __aenter__(self) -> FileAudioSource:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[AudioFrame]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AudioFrame]:
        if self._samples is None:
            await self.open()
        assert self._samples is not None
        position = 0
        started = self._clock()
        while not self._closed:
            if position >= self._samples.size:
                if not self.config.loop:
                    return
                position = 0
            end = min(position + self.chunk_size, self._samples.size)
            chunk = self._samples[position:end]
            if self.config.realtime:
                due = started + position / 16_000
                await self._sleep(max(0.0, due - self._clock()))
            yield AudioFrame(chunk, position / 16_000, self.config.id)
            position = end


FileSource = FileAudioSource
