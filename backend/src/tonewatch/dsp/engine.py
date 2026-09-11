"""Facade combining spectrum, segmentation, and matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np

from tonewatch.dsp.matcher import Detection, Matcher
from tonewatch.dsp.segmenter import Segmenter, ToneSegment
from tonewatch.dsp.spectrum import SpectrumAnalyzer, SpectrumFrame

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from tonewatch.config.models import ToneSet


@dataclass(frozen=True, slots=True)
class EngineOutput:
    """New frames, segment changes, and detections from one audio chunk."""

    frames: tuple[SpectrumFrame, ...]
    segments: tuple[ToneSegment, ...]
    detections: tuple[Detection, ...]


class DetectionEngine:
    """Pure streaming detection engine; no I/O, clock, or asyncio."""

    def __init__(self, tonesets: list[ToneSet] | tuple[ToneSet, ...], **tuning: object) -> None:
        """Create the three pure streaming stages with optional tuning."""
        self.spectrum = SpectrumAnalyzer(
            sample_rate=cast("int", tuning.get("sample_rate", 16_000)),
            window=cast("int", tuning.get("window", 4096)),
            hop=cast("int", tuning.get("hop", 1600)),
            band=cast("tuple[float, float]", tuning.get("band", (250, 3000))),
            purity_min=cast("float", tuning.get("purity_min", 0.6)),
            level_min_dbfs=cast("float", tuning.get("level_min_dbfs", -45)),
        )
        self.segmenter = Segmenter(
            tol_pct=cast("float", tuning.get("segment_tol_pct", 1.0)),
            max_dropout_frames=cast("int", tuning.get("max_dropout_frames", 2)),
        )
        self.matcher = Matcher(tonesets)

    def feed(self, samples: NDArray[np.float32]) -> EngineOutput:
        """Process a chunk and return only results newly produced by that chunk."""
        frames = self.spectrum.feed(np.asarray(samples, dtype=np.float32))
        update = self.segmenter.feed(frames)
        segments_by_start = {
            round(segment.start_s, 6): segment
            for segment in (*update.opened, *update.extended, *update.closed)
        }
        segments = tuple(segments_by_start.values())
        detections = tuple(self.matcher.feed(update))
        return EngineOutput(tuple(frames), segments, detections)
