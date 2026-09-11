"""Soundcard source using a non-blocking sounddevice callback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from importlib import import_module
from typing import Any, cast

import numpy as np

from tonewatch.config.models import SoundcardSource as SoundcardConfig
from tonewatch.sources.base import AudioFrame, SourceConfigError, SourceUnavailable
from tonewatch.sources.resample import resample_audio

sd: Any = import_module("sounddevice")

LOGGER = logging.getLogger(__name__)


def input_devices() -> list[dict[str, object]]:
    """Return normalized input-device details for the CLI and API."""
    devices: list[dict[str, object]] = []
    for index, item in enumerate(cast("list[dict[str, Any]]", sd.query_devices())):
        if int(item.get("max_input_channels", 0)) <= 0:
            continue
        hostapis = cast("list[dict[str, Any]]", sd.query_hostapis())
        host_index = int(item.get("hostapi", 0))
        devices.append(
            {
                "index": index,
                "name": str(item["name"]),
                "host_api": str(hostapis[host_index]["name"]),
                "max_input_channels": int(item["max_input_channels"]),
                "default_rate": float(item["default_samplerate"]),
            }
        )
    return devices


class SoundcardSource:
    """Capture a soundcard and normalize callback blocks."""

    def __init__(
        self,
        config: SoundcardConfig,
        *,
        queue_size: int = 8,
        stream_factory: Callable[..., Any] = sd.InputStream,
    ) -> None:
        self.config, self._queue = config, asyncio.Queue[np.ndarray](maxsize=queue_size)
        self._stream_factory = stream_factory
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sample_rate = 16_000
        self.dropped = 0
        self._closed = False

    def _select_device(self) -> tuple[int, dict[str, Any]]:
        devices = input_devices()
        selected = self.config.device
        if isinstance(selected, int):
            matches = [device for device in devices if device["index"] == selected]
        else:
            term = selected.casefold()
            matches = [device for device in devices if term in str(device["name"]).casefold()]
        if not matches:
            raise SourceConfigError(f"input device not found: {selected}")
        device = matches[0]
        return cast("int", device["index"]), cast("dict[str, Any]", device)

    async def open(self) -> None:
        self._loop = asyncio.get_running_loop()
        index, details = self._select_device()
        self._sample_rate = int(float(details["default_rate"]))
        channels = 2 if self.config.channel == "mix" else 1
        try:
            self._stream = self._stream_factory(
                device=index,
                samplerate=self._sample_rate,
                channels=channels,
                dtype="float32",
                callback=self._callback,
                blocksize=0,
            )
            self._stream.start()
        except Exception as exc:
            raise SourceUnavailable(f"could not open input device {self.config.device}") from exc
        self._closed = False

    def _callback(self, data: Any, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info
        if status:
            LOGGER.warning("soundcard status for %s: %s", self.config.id, status)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                self._enqueue, np.asarray(data, dtype=np.float32).copy()
            )

    def _enqueue(self, data: np.ndarray) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
            LOGGER.warning(
                "dropping oldest soundcard audio block for %s (dropped=%d)",
                self.config.id,
                self.dropped,
            )
        self._queue.put_nowait(data)

    async def close(self) -> None:
        self._closed = True
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def __aenter__(self) -> SoundcardSource:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[AudioFrame]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AudioFrame]:
        position = 0
        while not self._closed:
            block = await self._queue.get()
            if self.config.channel == "left":
                selected = block[:, 0]
            elif self.config.channel == "right":
                selected = block[:, 1] if block.shape[1] > 1 else block[:, 0]
            else:
                selected = block
            samples = resample_audio(selected, self._sample_rate)
            yield AudioFrame(samples, position / 16_000, self.config.id)
            position += samples.size


SoundcardAudioSource = SoundcardSource
