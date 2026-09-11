"""RTL-SDR source backed by rtl_fm."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable

import numpy as np

from tonewatch.config.models import RtlSdrSource as RtlConfig
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable


class RtlSdrSource:
    """Read signed 16-bit PCM from rtl_fm, restarting after exit."""

    def __init__(
        self,
        config: RtlConfig,
        *,
        executable: str = "rtl_fm",
        prefix_args: tuple[str, ...] = (),
        sample_rate: int = 48_000,
        chunk_size: int = 1600,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config, self.executable, self.prefix_args, self.sample_rate = (
            config,
            executable,
            prefix_args,
            sample_rate,
        )
        self.chunk_size, self._sleep = chunk_size, sleep
        self._process: asyncio.subprocess.Process | None = None
        self.last_process: asyncio.subprocess.Process | None = None
        self._closed = False
        self._position = 0

    def argv(self) -> list[str]:
        return [
            self.executable,
            *self.prefix_args,
            "-f",
            str(self.config.freq_hz),
            "-M",
            "fm",
            "-s",
            str(self.sample_rate),
            "-r",
            "16000",
            "-g",
            str(self.config.gain if self.config.gain is not None else 0),
            "-p",
            str(self.config.ppm),
            "-l",
            str(self.config.squelch),
            "-",
        ]

    async def open(self) -> None:
        if shutil.which(self.executable) is None:
            raise SourceConfigError(f"rtl_fm executable not found: {self.executable}")
        self._closed = False

    async def close(self) -> None:
        self._closed = True
        if self._process is not None and self._process.returncode is None:
            self._process.kill()
        if self._process is not None:
            await self._process.wait()
        self._process = None

    async def __aenter__(self) -> RtlSdrSource:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[AudioFrame]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AudioFrame]:
        delay = 1.0
        while not self._closed:
            self._process = await asyncio.create_subprocess_exec(
                *self.argv(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            self.last_process = self._process
            if self._process.stdout is None:
                raise SourceUnavailable("rtl_fm did not provide stdout")
            while not self._closed:
                raw = await self._process.stdout.read(self.chunk_size * 2)
                if not raw:
                    break
                usable = len(raw) - len(raw) % 2
                if usable:
                    samples = (
                        np.frombuffer(raw[:usable], dtype="<i2").astype(np.float32) / 32768
                    ).astype(np.float32)
                    yield AudioFrame(samples, self._position / 16_000, self.config.id)
                    self._position += samples.size
            await self._process.wait()
            self._process = None
            if self._closed:
                return
            await self._sleep(delay)
            delay = min(60.0, delay * 2)


RtlSdrAudioSource = RtlSdrSource
