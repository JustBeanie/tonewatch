"""Pure streaming discovery of tone sequences not claimed by configured sets."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tonewatch.config.models import ToneSet, ToneSpec
    from tonewatch.dsp.matcher import Detection
    from tonewatch.dsp.segmenter import SegmenterUpdate, ToneSegment


@dataclass(frozen=True, slots=True)
class ToneCandidate:
    """A finalized, unmatched tonal sequence."""

    segments: tuple[ToneSegment, ...]

    @property
    def frequencies(self) -> tuple[float, ...]:
        """Return the dominant frequencies in sequence order."""
        return tuple(segment.freq_hz for segment in self.segments)

    @property
    def durations(self) -> tuple[float, ...]:
        """Return segment durations in sequence order."""
        return tuple(segment.duration_s for segment in self.segments)

    @property
    def start_s(self) -> float:
        """Return the first segment start time."""
        return self.segments[0].start_s

    @property
    def end_s(self) -> float:
        """Return the last segment end time."""
        return self.segments[-1].end_s

    @property
    def mean_purity(self) -> float:
        """Return the arithmetic mean segment purity."""
        return sum(item.mean_purity for item in self.segments) / len(self.segments)


class DiscoveryTracker:
    """Buffer stable segments and emit finalized unmatched tone candidates.

    ``known_tonesets`` contains every set configured by the user, including
    disabled sets and sets assigned to another source. Those definitions are
    still suppressed from discovery because they are known pages, even when
    the source's matcher did not emit a detection.
    """

    def __init__(
        self,
        *,
        max_gap_s: float = 0.5,
        min_segment_s: float = 0.3,
        max_segment_s: float = 3.0,
        purity_min: float = 0.6,
        level_min_dbfs: float = -45.0,
        max_buffered_segments: int = 256,
        max_candidate_tones: int = 5,
        known_tonesets: Sequence[ToneSet] = (),
    ) -> None:
        if max_gap_s < 0 or min_segment_s <= 0 or max_segment_s < min_segment_s:
            raise ValueError("invalid discovery timing configuration")
        if max_buffered_segments < 1 or max_candidate_tones < 1:
            raise ValueError("discovery caps must be positive")
        self.max_gap_s = max_gap_s
        self.min_segment_s = min_segment_s
        self.max_segment_s = max_segment_s
        self.purity_min = purity_min
        self.level_min_dbfs = level_min_dbfs
        self.max_buffered_segments = max_buffered_segments
        self.max_candidate_tones = max_candidate_tones
        self.known_tonesets = tuple(known_tonesets)
        self._buffer: list[ToneSegment] = []
        self._active: list[ToneSegment] = []
        self._seen: set[tuple[float, float, float]] = set()
        self._matched_spans: deque[tuple[float, float]] = deque(maxlen=max_buffered_segments * 2)
        self._pending_open_start: float | None = None

    @property
    def buffered_segment_count(self) -> int:
        """Return the number of retained segments, for bounded-memory checks."""
        return len(self._buffer) + len(self._active)

    def feed(
        self,
        update: SegmenterUpdate,
        detections: Sequence[Detection] = (),
        now_s: float = 0.0,
    ) -> list[ToneCandidate]:
        """Consume one segment update and return candidates whose gap has elapsed."""
        if update.opened or update.extended:
            self._pending_open_start = min(
                segment.start_s for segment in (*update.opened, *update.extended)
            )
        for detection in detections:
            self._matched_spans.extend(
                (segment.start_s, segment.end_s) for segment in detection.segments
            )
        for segment in update.closed:
            if (
                self._pending_open_start is not None
                and abs(segment.start_s - self._pending_open_start) <= 1e-6
            ):
                self._pending_open_start = None
            if not self._passes_gate(segment):
                continue
            key = (round(segment.start_s, 6), round(segment.end_s, 6), round(segment.freq_hz, 3))
            if key in self._seen:
                continue
            self._seen.add(key)
            self._buffer.append(segment)
        self._trim_memory()
        emitted: list[ToneCandidate] = []
        for segment in sorted(self._buffer, key=lambda item: item.start_s):
            if self._active and segment.start_s - self._active[-1].end_s > self.max_gap_s:
                emitted.extend(self._finalize(self._active))
                self._active = []
            if not self._active:
                self._active = [segment]
            elif len(self._active) < self.max_candidate_tones:
                self._active.append(segment)
            else:
                emitted.extend(self._finalize(self._active))
                self._active = [segment]
        self._buffer.clear()
        pending_nearby = (
            self._pending_open_start is not None
            and self._pending_open_start - self._active[-1].end_s <= self.max_gap_s
            if self._active
            else False
        )
        if self._active and now_s > self._active[-1].end_s + self.max_gap_s and not pending_nearby:
            emitted.extend(self._finalize(self._active))
            self._active = []
        return emitted

    def _passes_gate(self, segment: ToneSegment) -> bool:
        return (
            250 <= segment.freq_hz <= 3000
            and segment.mean_purity >= self.purity_min
            and segment.mean_level_dbfs >= self.level_min_dbfs
            and segment.duration_s >= self.min_segment_s
        )

    def _trim_memory(self) -> None:
        excess = self.buffered_segment_count - self.max_buffered_segments
        if excess <= 0:
            return
        while excess and self._active:
            dropped = self._active.pop(0)
            self._seen.discard(self._key(dropped))
            excess -= 1
        while excess and self._buffer:
            dropped = self._buffer.pop(0)
            self._seen.discard(self._key(dropped))
            excess -= 1

    @staticmethod
    def _key(segment: ToneSegment) -> tuple[float, float, float]:
        return (round(segment.start_s, 6), round(segment.end_s, 6), round(segment.freq_hz, 3))

    def _finalize(self, segments: list[ToneSegment]) -> list[ToneCandidate]:
        self._seen.difference_update(
            (round(item.start_s, 6), round(item.end_s, 6), round(item.freq_hz, 3))
            for item in segments
        )
        known_spans = (*self._matched_spans, *self._known_spans(segments))
        runs: list[list[ToneSegment]] = [[]]
        for segment in segments:
            if any(self._overlap(segment.start_s, segment.end_s, span) for span in known_spans):
                if runs[-1]:
                    runs.append([])
                continue
            runs[-1].append(segment)
        return [ToneCandidate(tuple(run)) for run in runs if self._valid_shape(run)]

    def _known_spans(self, segments: list[ToneSegment]) -> list[tuple[float, float]]:
        """Return spans matching any configured definition, regardless of status."""
        ordered = tuple(sorted(segments, key=lambda item: item.start_s))
        spans: list[tuple[float, float]] = []
        for toneset in self.known_tonesets:
            sequence = toneset.sequence
            if len(sequence) == 1:
                spec = sequence[0]
                spans.extend(
                    (segment.start_s, segment.end_s)
                    for segment in ordered
                    if self._matches(segment, spec) and self._in_duration(segment, spec)
                )
                continue
            for final in ordered:
                if not self._matches(final, sequence[-1]) or not self._in_duration(
                    final, sequence[-1]
                ):
                    continue
                chain = [final]
                cursor = final
                for spec in reversed(sequence[:-1]):
                    candidates = [
                        segment
                        for segment in ordered
                        if segment.end_s <= cursor.start_s
                        and self._matches(segment, spec)
                        and self._in_duration(segment, spec)
                        and 0 <= cursor.start_s - segment.end_s <= toneset.max_gap_s
                    ]
                    if not candidates:
                        break
                    cursor = candidates[-1]
                    chain.append(cursor)
                else:
                    chain.reverse()
                    spans.append((chain[0].start_s, chain[-1].end_s))
        return spans

    @staticmethod
    def _matches(segment: ToneSegment, spec: ToneSpec) -> bool:
        return abs(segment.freq_hz - spec.freq_hz) <= spec.freq_hz * spec.tol_pct / 100

    @staticmethod
    def _in_duration(segment: ToneSegment, spec: ToneSpec) -> bool:
        return segment.duration_s + 1e-6 >= spec.min_s and (
            spec.max_s is None or segment.duration_s <= spec.max_s + 1e-6
        )

    def _valid_shape(self, segments: list[ToneSegment]) -> bool:
        if not segments or len(segments) > self.max_candidate_tones:
            return False
        if len(segments) == 1:
            return segments[0].duration_s >= 2.0
        return all(self.min_segment_s <= item.duration_s <= self.max_segment_s for item in segments)

    @staticmethod
    def _overlap(start: float, end: float, span: tuple[float, float]) -> bool:
        return start < span[1] and end > span[0]
