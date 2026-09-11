"""Tonal frame grouping with short dropout tolerance."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tonewatch.dsp.spectrum import SpectrumFrame


@dataclass(slots=True)
class ToneSegment:
    """A contiguous tone; ``excess_s`` is populated by the matcher if needed."""

    freq_hz: float
    start_s: float
    end_s: float
    mean_purity: float
    closed: bool
    excess_s: float = 0.0

    @property
    def duration_s(self) -> float:
        """Return duration after compensating for the FFT window smear."""
        return max(0.0, self.end_s - self.start_s)


@dataclass(frozen=True, slots=True)
class SegmenterUpdate:
    """Changes emitted by one call to :meth:`Segmenter.feed`."""

    opened: tuple[ToneSegment, ...] = ()
    extended: tuple[ToneSegment, ...] = ()
    closed: tuple[ToneSegment, ...] = ()


class Segmenter:
    """Group nearby tonal frames, bridging up to ``max_dropout_frames`` gaps."""

    def __init__(self, tol_pct: float = 1.0, max_dropout_frames: int = 2) -> None:
        if tol_pct <= 0 or max_dropout_frames < 0:
            raise ValueError("invalid segmenter configuration")
        self.tol_pct = tol_pct
        self.max_dropout_frames = max_dropout_frames
        self._current: ToneSegment | None = None
        self._dropouts = 0
        self._frequencies: list[float] = []
        self._purity_count = 0

    def _matches(self, frequency: float) -> bool:
        if self._current is None:
            return False
        center = median(self._frequencies[-7:])
        return abs(frequency - center) <= center * self.tol_pct / 100

    def _close(self, closed: list[ToneSegment]) -> None:
        if self._current is not None:
            current = self._current
            closed.append(
                ToneSegment(
                    freq_hz=current.freq_hz,
                    start_s=current.start_s,
                    end_s=current.end_s,
                    mean_purity=current.mean_purity,
                    closed=True,
                    excess_s=current.excess_s,
                )
            )
            self._current = None
            self._frequencies = []
            self._purity_count = 0
            self._dropouts = 0

    def feed(self, frames: Iterable[SpectrumFrame]) -> SegmenterUpdate:
        """Consume frames and expose open, extended, and closed segments."""
        opened: list[ToneSegment] = []
        extended: list[ToneSegment] = []
        closed: list[ToneSegment] = []
        for frame in frames:
            if frame.tonal:
                if self._current is None or not self._matches(frame.freq_hz):
                    self._close(closed)
                    self._current = ToneSegment(
                        freq_hz=frame.freq_hz,
                        # A Hann window smears both edges by roughly half its
                        # width; center timestamps restore duration accuracy.
                        start_s=max(0.0, frame.t_end_s - frame.window_s / 2),
                        end_s=frame.t_end_s - frame.window_s / 2,
                        mean_purity=frame.purity,
                        closed=False,
                    )
                    self._frequencies = [frame.freq_hz]
                    self._purity_count = 1
                    self._dropouts = 0
                    opened.append(self._current)
                else:
                    self._frequencies.append(frame.freq_hz)
                    self._purity_count += 1
                    self._current.freq_hz = float(median(self._frequencies[-7:]))
                    self._current.end_s = frame.t_end_s - frame.window_s / 2
                    self._current.mean_purity = (
                        self._current.mean_purity * (self._purity_count - 1) + frame.purity
                    ) / self._purity_count
                    self._current.closed = False
                    extended.append(self._current)
                continue
            if self._current is not None:
                self._dropouts += 1
                if self._dropouts > self.max_dropout_frames:
                    self._close(closed)
        return SegmenterUpdate(tuple(opened), tuple(extended), tuple(closed))
