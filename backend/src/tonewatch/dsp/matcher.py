"""Per-tone-set sequence matching with early pre-alerts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tonewatch.config.models import ToneSet, ToneSpec
    from tonewatch.dsp.segmenter import SegmenterUpdate, ToneSegment


@dataclass(slots=True)
class Detection:
    """One tone-set detection, emitted at the earliest valid time."""

    toneset_id: str
    detected_at_s: float
    segments: tuple[ToneSegment, ...]
    early: bool


class Matcher:
    """Match completed or still-open segments against configured tone sets."""

    def __init__(self, tonesets: list[ToneSet] | tuple[ToneSet, ...]) -> None:
        self.tonesets = tuple(tonesets)
        self._segments: dict[float, ToneSegment] = {}
        self._emitted: set[tuple[str, float]] = set()
        self._last_detected: dict[str, float] = {}
        self._detections: list[Detection] = []

    @staticmethod
    def _key(segment: ToneSegment) -> float:
        return round(segment.start_s, 6)

    @staticmethod
    def _matches(segment: ToneSegment, spec: ToneSpec) -> bool:
        return abs(segment.freq_hz - spec.freq_hz) <= spec.freq_hz * spec.tol_pct / 100

    @staticmethod
    def _in_duration(segment: ToneSegment, spec: ToneSpec) -> bool:
        epsilon = 1e-6
        return segment.duration_s + epsilon >= spec.min_s and (
            spec.max_s is None or segment.duration_s <= spec.max_s + epsilon
        )

    def _cooldown_allows(self, toneset: ToneSet, detected_at_s: float) -> bool:
        previous = self._last_detected.get(toneset.id)
        return previous is None or detected_at_s - previous >= toneset.cooldown_s

    def _emit(
        self, toneset: ToneSet, detected_at_s: float, segments: tuple[ToneSegment, ...]
    ) -> Detection:
        detection = Detection(toneset.id, detected_at_s, segments, early=True)
        self._last_detected[toneset.id] = detected_at_s
        self._detections.append(detection)
        return detection

    def _update_excess(self) -> None:
        for detection in self._detections:
            toneset = next(item for item in self.tonesets if item.id == detection.toneset_id)
            for segment, spec in zip(detection.segments, toneset.sequence, strict=False):
                segment.excess_s = max(0.0, segment.duration_s - spec.max_s) if spec.max_s else 0.0

    def _find_chain(
        self, ordered: tuple[ToneSegment, ...], toneset: ToneSet, final: ToneSegment
    ) -> tuple[ToneSegment, ...] | None:
        """Find the nearest valid predecessor for every tone in the sequence."""
        chain = [final]
        cursor = final
        for spec in reversed(toneset.sequence[:-1]):
            candidates = [
                segment
                for segment in ordered
                if segment.end_s <= cursor.start_s
                and self._matches(segment, spec)
                and self._in_duration(segment, spec)
                and 0 <= cursor.start_s - segment.end_s <= toneset.max_gap_s
            ]
            if not candidates:
                return None
            cursor = candidates[-1]
            chain.append(cursor)
        return tuple(reversed(chain))

    def feed(self, update: SegmenterUpdate) -> list[Detection]:
        """Consume segment updates and emit only newly valid detections."""
        for segment in (*update.opened, *update.extended, *update.closed):
            self._segments[self._key(segment)] = segment
        ordered = tuple(sorted(self._segments.values(), key=lambda segment: segment.start_s))
        new_detections: list[Detection] = []
        for toneset in self.tonesets:
            if not toneset.enabled:
                continue
            sequence = toneset.sequence
            if len(sequence) == 1:
                spec = sequence[0]
                for segment in ordered:
                    key = (toneset.id, self._key(segment))
                    if key in self._emitted or not self._matches(segment, spec):
                        continue
                    if segment.duration_s + 1e-6 >= spec.min_s:
                        detected_at = segment.start_s + spec.min_s
                        if self._cooldown_allows(toneset, detected_at):
                            new_detections.append(self._emit(toneset, detected_at, (segment,)))
                            self._emitted.add(key)
                continue
            final_spec = sequence[-1]
            for final_segment in ordered:
                final_key = (toneset.id, self._key(final_segment))
                if final_key in self._emitted or not self._matches(final_segment, final_spec):
                    continue
                if final_segment.duration_s + 1e-6 < final_spec.min_s:
                    continue
                segments = self._find_chain(ordered, toneset, final_segment)
                if segments is None:
                    continue
                detected_at = final_segment.start_s + final_spec.min_s
                if self._cooldown_allows(toneset, detected_at):
                    new_detections.append(self._emit(toneset, detected_at, segments))
                    self._emitted.add(final_key)
        self._update_excess()
        return new_detections
