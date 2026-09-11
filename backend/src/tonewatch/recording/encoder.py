"""Atomic PyAV encoders for normalized mono call audio."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import av
import numpy as np


@dataclass(frozen=True, slots=True)
class EncodedRecording:
    path: Path
    format: str
    duration_s: float
    size_bytes: int


class AudioEncoder:
    """Encode audio off the event loop and replace files atomically."""

    def __init__(self, recordings_root: Path) -> None:
        self.recordings_root = recordings_root

    async def encode(
        self,
        samples: np.ndarray,
        *,
        call_id: str,
        call_start: datetime,
        formats: set[str] | frozenset[str],
        title: str,
        toneset_ids: set[str] | frozenset[str],
        source_id: str,
    ) -> list[EncodedRecording]:
        return await asyncio.to_thread(
            self._encode_sync,
            np.asarray(samples, dtype=np.float32),
            call_id,
            call_start,
            formats,
            title,
            toneset_ids,
            source_id,
        )

    def _encode_sync(
        self,
        samples: np.ndarray,
        call_id: str,
        call_start: datetime,
        formats: set[str] | frozenset[str],
        title: str,
        toneset_ids: set[str] | frozenset[str],
        source_id: str,
    ) -> list[EncodedRecording]:
        day = call_start.astimezone(UTC).date()
        directory = self.recordings_root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
        directory.mkdir(parents=True, exist_ok=True)
        result: list[EncodedRecording] = []
        for fmt in sorted(formats):
            if fmt not in {"mp3", "opus"}:
                raise ValueError(f"unsupported recording format: {fmt}")
            ext = "mp3" if fmt == "mp3" else "ogg"
            path = directory / f"{call_id}.{ext}"
            fd, temporary = tempfile.mkstemp(
                prefix=f".{call_id}.", suffix=f".{ext}.tmp", dir=directory
            )
            os.close(fd)
            try:
                self._write(
                    path=Path(temporary),
                    samples=samples,
                    fmt=fmt,
                    title=title,
                    toneset_ids=toneset_ids,
                    source_id=source_id,
                    call_id=call_id,
                )
                os.replace(temporary, path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
            result.append(EncodedRecording(path, fmt, samples.size / 16_000, path.stat().st_size))
        return result

    @staticmethod
    def _write(
        path: Path,
        samples: np.ndarray,
        fmt: str,
        title: str,
        toneset_ids: set[str] | frozenset[str],
        source_id: str,
        call_id: str,
    ) -> None:
        codec = "mp3" if fmt == "mp3" else "libopus"
        with av.open(str(path), mode="w", format="mp3" if fmt == "mp3" else "ogg") as container:
            stream = cast("Any", container.add_stream(codec, rate=16_000))
            stream.layout = "mono"
            stream.bit_rate = 32_000 if fmt == "mp3" else 24_000
            container.metadata.update(
                {
                    "title": title,
                    "tone_set_ids": ",".join(sorted(toneset_ids)),
                    "source_id": source_id,
                    "call_id": call_id,
                }
            )
            pcm = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = 16_000
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
