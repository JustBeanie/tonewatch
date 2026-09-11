"""Pure, deterministic digital signal processing for ToneWatch."""

from tonewatch.dsp.engine import DetectionEngine, EngineOutput
from tonewatch.dsp.matcher import Detection, Matcher
from tonewatch.dsp.segmenter import Segmenter, SegmenterUpdate, ToneSegment
from tonewatch.dsp.spectrum import SpectrumAnalyzer, SpectrumFrame

__all__ = [
    "Detection",
    "DetectionEngine",
    "EngineOutput",
    "Matcher",
    "Segmenter",
    "SegmenterUpdate",
    "SpectrumAnalyzer",
    "SpectrumFrame",
    "ToneSegment",
]
