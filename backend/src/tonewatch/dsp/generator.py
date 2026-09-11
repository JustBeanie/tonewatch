"""Deterministic float32 signal generators used by tests and the CLI."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16_000
Signal = NDArray[np.float32]

if TYPE_CHECKING:
    from collections.abc import Iterable


def _samples(duration_s: float) -> int:
    if duration_s < 0:
        raise ValueError("duration must not be negative")
    return round(duration_s * SAMPLE_RATE)


def tone(freq_hz: float, dur_s: float, amp: float = 1.0) -> Signal:
    """Return a sine tone at the project sample rate."""
    if freq_hz <= 0 or amp < 0:
        raise ValueError("frequency must be positive and amplitude non-negative")
    samples = np.arange(_samples(dur_s), dtype=np.float64) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq_hz * samples)).astype(np.float32)


def silence(dur_s: float) -> Signal:
    """Return digital silence."""
    return np.zeros(_samples(dur_s), dtype=np.float32)


def white_noise(dur_s: float, amp: float = 1.0, seed: int = 0) -> Signal:
    """Return seeded white Gaussian noise."""
    return (np.random.default_rng(seed).standard_normal(_samples(dur_s)) * amp).astype(np.float32)


def pink_noise(dur_s: float, amp: float = 1.0, seed: int = 0) -> Signal:
    """Return seeded 1/f-shaped noise."""
    count = _samples(dur_s)
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.standard_normal(count))
    frequencies = np.fft.rfftfreq(count)
    scale = np.ones_like(frequencies)
    scale[1:] = 1 / np.sqrt(frequencies[1:])
    result = np.fft.irfft(spectrum * scale, n=count)
    result /= max(float(np.std(result)), 1e-12)
    return (result * amp).astype(np.float32)


def voice_like(dur_s: float, seed: int = 0) -> Signal:
    """Return speech-like interference with continuously gliding harmonics.

    The fundamental is modulated at several hertz and glides every few cycles;
    consequently this signal never holds one pure tone for 150 ms. A filtered
    noise component supplies formant-like consonant energy.
    """
    count = _samples(dur_s)
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    rng = np.random.default_rng(seed)
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    phase = rng.uniform(0, 2 * np.pi)
    f0 = 175 + 55 * np.sin(2 * np.pi * 1.3 * time + phase)
    f0 += 18 * np.sin(2 * np.pi * 3.7 * time + phase / 2)
    fundamental_phase = 2 * np.pi * np.cumsum(f0) / SAMPLE_RATE
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 2.1 * time + phase) ** 2
    harmonic = sum(
        (1 / harmonic_number)
        * np.sin(harmonic_number * fundamental_phase + rng.uniform(0, 2 * np.pi))
        for harmonic_number in range(1, 7)
    )
    raw_noise = rng.standard_normal(count)
    noise_spectrum = np.fft.rfft(raw_noise)
    frequencies = np.fft.rfftfreq(count, 1 / SAMPLE_RATE)
    band = (frequencies >= 250) & (frequencies <= 3500)
    filtered_noise = np.fft.irfft(noise_spectrum * band, n=count)
    filtered_noise /= max(float(np.std(filtered_noise)), 1e-12)
    result = 0.16 * envelope * harmonic + 0.06 * filtered_noise
    result /= max(float(np.max(np.abs(result))), 1e-12) / 0.55
    return result.astype(np.float32)


def add_noise(signal: Signal, snr_db: float, seed: int = 0) -> Signal:
    """Add seeded white noise at the requested RMS signal-to-noise ratio."""
    source = np.asarray(signal, dtype=np.float32)
    signal_power = float(np.mean(source.astype(np.float64) ** 2))
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = np.random.default_rng(seed).standard_normal(source.size) * np.sqrt(noise_power)
    return (source + noise).astype(np.float32)


def clip(signal: Signal, level: float) -> Signal:
    """Hard-clip a signal to +/- ``level``."""
    if level <= 0:
        raise ValueError("clip level must be positive")
    return np.clip(signal, -level, level).astype(np.float32)


def phase_jump(signal: Signal, at_s: float) -> Signal:
    """Apply a deterministic 180-degree phase discontinuity at ``at_s``."""
    if at_s < 0:
        raise ValueError("phase jump must not be negative")
    result = np.asarray(signal, dtype=np.float32).copy()
    result[_samples(at_s) :] *= -1
    return result


def concat(*signals: Signal) -> Signal:
    """Concatenate signals without changing their sample rate or dtype."""
    if not signals:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate([np.asarray(signal, dtype=np.float32) for signal in signals]).astype(
        np.float32
    )


def jitter(dur_s: float, max_s: float, seed: int = 0) -> float:
    """Return a seeded duration jittered uniformly around ``dur_s``."""
    if max_s < 0:
        raise ValueError("maximum jitter must not be negative")
    return max(0.0, float(dur_s + np.random.default_rng(seed).uniform(-max_s, max_s)))


def _write_wav(path: Path, signal: Signal) -> None:
    pcm = np.clip(signal, -1, 1)
    encoded = (pcm * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(encoded)


def main(argv: Iterable[str] | None = None) -> None:
    """Generate a WAV containing one deterministic tone or silence."""
    parser = argparse.ArgumentParser(prog="tonewatch-gen")
    parser.add_argument("output", type=Path)
    parser.add_argument("--tone", type=float)
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--amp", type=float, default=0.5)
    args = parser.parse_args(argv)
    signal = tone(args.tone, args.duration, args.amp) if args.tone else silence(args.duration)
    _write_wav(args.output, signal)
