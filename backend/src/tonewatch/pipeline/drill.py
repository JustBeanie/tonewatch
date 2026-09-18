"""Synthetic audio used by the authenticated end-to-end drill."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tonewatch.dsp.generator import SAMPLE_RATE, Signal, concat, tone, voice_like

MAX_VOICE_S = 20


@dataclass(frozen=True, slots=True)
class DrillWaveform:
    """A normalized synthetic waveform and its playback duration."""

    samples: Signal
    expected_duration_s: float


def build_waveform(
    sequence: list[tuple[float, float, float]] | tuple[tuple[float, float, float], ...],
    *,
    voice_s: float = 5.0,
    seed: int = 0,
) -> DrillWaveform:
    """Build a bounded, non-clipping sequence from (frequency, min, max) values."""
    if not 0 <= voice_s <= MAX_VOICE_S:
        raise ValueError("voice_s must be between 0 and 20 seconds")
    parts: list[Signal] = []
    for frequency, min_s, max_s in sequence:
        if frequency <= 0 or min_s <= 0 or max_s < min_s:
            raise ValueError("duration bounds are invalid")
        safe_duration = min(max_s, max(min_s + 0.3, min_s + 0.5 * (max_s - min_s)))
        parts.append(tone(frequency, safe_duration, 0.72))
    if voice_s:
        parts.append(voice_like(voice_s, seed=seed) * np.float32(0.35))
    samples = np.clip(concat(*parts), -1.0, 1.0).astype(np.float32)
    return DrillWaveform(samples, samples.size / SAMPLE_RATE)
