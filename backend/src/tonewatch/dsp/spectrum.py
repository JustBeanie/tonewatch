"""Incremental FFT spectrum analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class SpectrumFrame:
    """One analyzed window; ``t_end_s`` is the source-window end time."""

    t_end_s: float
    freq_hz: float
    level_dbfs: float
    purity: float
    tonal: bool
    window_s: float = 4096 / 16_000


class SpectrumAnalyzer:
    """Frame float32 audio with a Hann window and estimate its dominant tone."""

    def __init__(
        self,
        sample_rate: int = 16_000,
        window: int = 4096,
        hop: int = 1600,
        band: tuple[float, float] = (250, 3000),
        purity_min: float = 0.6,
        level_min_dbfs: float = -45,
    ) -> None:
        """Create an analyzer with the specified framing and detection thresholds."""
        if window <= 2 or hop <= 0 or band[0] >= band[1]:
            raise ValueError("invalid spectrum configuration")
        self.sample_rate = sample_rate
        self.window = window
        self.hop = hop
        self.band = band
        self.purity_min = purity_min
        self.level_min_dbfs = level_min_dbfs
        self._pending = np.zeros(0, dtype=np.float32)
        self._next_start = 0
        self._window = np.hanning(window).astype(np.float64)
        frequencies = np.fft.rfftfreq(window, 1 / sample_rate)
        self._frequencies = frequencies
        self._lo = int(np.searchsorted(frequencies, band[0], side="left"))
        self._hi = int(np.searchsorted(frequencies, band[1], side="right"))

    def feed(self, samples: NDArray[np.float32]) -> list[SpectrumFrame]:
        """Consume any-sized chunks and return every newly complete frame.

        The unconsumed tail remains buffered, so chunk boundaries cannot affect
        FFT values or timestamps.
        """
        incoming = np.asarray(samples, dtype=np.float32).reshape(-1)
        if incoming.size:
            self._pending = np.concatenate((self._pending, incoming))
        frames: list[SpectrumFrame] = []
        while self._pending.size >= self.window:
            windowed = self._pending[: self.window].astype(np.float64)
            magnitudes = np.abs(np.fft.rfft(windowed * self._window))
            band_magnitudes = magnitudes[self._lo : self._hi]
            peak_relative = int(np.argmax(band_magnitudes))
            peak_bin = self._lo + peak_relative
            peak_magnitude = max(float(magnitudes[peak_bin]), 1e-12)
            log_peak = np.log(max(peak_magnitude, 1e-12))
            if 0 < peak_bin < magnitudes.size - 1:
                left = np.log(max(float(magnitudes[peak_bin - 1]), 1e-12))
                right = np.log(max(float(magnitudes[peak_bin + 1]), 1e-12))
                denominator = left - 2 * log_peak + right
                offset = 0.5 * (left - right) / denominator if denominator else 0.0
            else:
                offset = 0.0
            frequency = float((peak_bin + offset) * self.sample_rate / self.window)
            energy = magnitudes[self._lo : self._hi] ** 2
            purity_start = max(self._lo, peak_bin - 2) - self._lo
            purity_end = min(self._hi, peak_bin + 3) - self._lo
            purity = float(
                np.sum(energy[purity_start:purity_end]) / max(float(np.sum(energy)), 1e-20)
            )
            rms = float(np.sqrt(np.mean(windowed**2)))
            level = float(20 * np.log10(max(rms, 1e-12)))
            frames.append(
                SpectrumFrame(
                    t_end_s=(self._next_start + self.window) / self.sample_rate,
                    freq_hz=frequency,
                    level_dbfs=level,
                    purity=purity,
                    tonal=purity >= self.purity_min and level >= self.level_min_dbfs,
                    window_s=self.window / self.sample_rate,
                )
            )
            self._pending = self._pending[self.hop :]
            self._next_start += self.hop
        return frames
