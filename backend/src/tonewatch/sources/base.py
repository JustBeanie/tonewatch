"""Common audio source contracts and factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from tonewatch.config.models import Source


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """A deterministic, normalized chunk of source audio."""

    samples: NDArray[np.float32]
    stream_time_s: float
    source_id: str
    discontinuity: bool = False


class SourceError(RuntimeError):
    """Base class for source failures."""


class SourceUnavailable(SourceError):
    """A source failed transiently and may be retried."""


class SourceConfigError(SourceError):
    """A source configuration cannot work and should not be retried."""


class AudioSource(Protocol):
    """Async source lifecycle and iterator protocol."""

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def __aiter__(self) -> AsyncIterator[AudioFrame]: ...
    async def __aenter__(self) -> AudioSource: ...
    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...


def make_source(config: Source, *, settings: Any = None) -> AudioSource:
    """Construct the source implementation matching a validated config."""
    from tonewatch.sources.file import FileAudioSource
    from tonewatch.sources.rtlsdr import RtlSdrSource
    from tonewatch.sources.soundcard import SoundcardSource
    from tonewatch.sources.stream import StreamAudioSource

    source_type = config.type
    if source_type == "file":
        return FileAudioSource(cast("Any", config))
    if source_type == "soundcard":
        return SoundcardSource(cast("Any", config))
    if source_type == "stream":
        return StreamAudioSource(cast("Any", config), settings=settings)
    if source_type == "rtlsdr":
        return RtlSdrSource(cast("Any", config))
    raise SourceConfigError(f"unsupported source type: {source_type}")


def as_float32(samples: NDArray[np.floating[Any]] | NDArray[np.float32]) -> NDArray[np.float32]:
    """Return contiguous float32 samples."""
    return np.ascontiguousarray(samples, dtype=np.float32)
