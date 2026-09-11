"""Shared deterministic audio normalization."""

from typing import Any

import numpy as np
from numpy.typing import NDArray

TARGET_RATE = 16_000


def resample_audio(samples: NDArray[Any], sample_rate: int) -> NDArray[np.float32]:
    """Mix channels and linearly resample audio to mono float32 at 16 kHz."""
    values = np.asarray(samples, dtype=np.float32)
    if values.ndim == 1:
        mono = values
    elif values.ndim == 2:
        mono = values.mean(axis=1, dtype=np.float32)
    else:
        raise ValueError("audio samples must be one- or two-dimensional")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if mono.size == 0 or sample_rate == TARGET_RATE:
        return np.ascontiguousarray(mono, dtype=np.float32)
    count = round(mono.size * TARGET_RATE / sample_rate)
    source_time = np.arange(mono.size, dtype=np.float64) / sample_rate
    target_time = np.arange(count, dtype=np.float64) / TARGET_RATE
    return np.interp(target_time, source_time, mono).astype(np.float32)


normalize_audio = resample_audio
