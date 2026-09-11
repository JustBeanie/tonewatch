"""Hypothesis properties for streaming DSP invariants."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tonewatch.config.models import ToneSet, ToneSpec
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import concat, silence, tone
from tonewatch.dsp.spectrum import SpectrumAnalyzer


def _page(freq_a: float, freq_b: float) -> ToneSet:
    return ToneSet(
        id="page",
        name="page",
        sequence=[
            ToneSpec(freq_hz=freq_a, tol_pct=1.5, min_s=0.8, max_s=1.4),
            ToneSpec(freq_hz=freq_b, tol_pct=1.5, min_s=1.8, max_s=3.5),
        ],
        max_gap_s=0.5,
    )


@settings(max_examples=8, deadline=None)
@given(st.sampled_from([1, 2, 7, 333, 1600, 5000]))
def test_spectrum_chunking_invariant(chunk_size: int) -> None:
    samples = concat(tone(700.25, 1.3, 0.4), silence(0.2), tone(1800.75, 0.9, 0.4))
    whole = SpectrumAnalyzer().feed(samples)
    analyzer = SpectrumAnalyzer()
    chunked = []
    for start in range(0, samples.size, chunk_size):
        chunked.extend(analyzer.feed(samples[start : start + chunk_size]))
    assert [(frame.t_end_s, frame.freq_hz, frame.purity) for frame in chunked] == [
        (frame.t_end_s, frame.freq_hz, frame.purity) for frame in whole
    ]


@settings(max_examples=8, deadline=None)
@given(
    st.floats(min_value=500, max_value=2400, allow_nan=False, allow_infinity=False),
    st.floats(min_value=500, max_value=2400, allow_nan=False, allow_infinity=False),
)
def test_valid_two_tone_is_detected_once(freq_a: float, freq_b: float) -> None:
    if abs(freq_a - freq_b) < 100:
        freq_b += 150
    engine = DetectionEngine([_page(freq_a, freq_b)])
    signal = concat(tone(freq_a * 1.005, 1.0, 0.5), silence(0.1), tone(freq_b * 0.995, 2.1, 0.5))
    detections = engine.feed(signal).detections
    assert len(detections) == 1


@settings(max_examples=8, deadline=None)
@given(st.floats(min_value=500, max_value=2400, allow_nan=False, allow_infinity=False))
def test_offset_at_least_two_tolerances_is_not_detected(freq: float) -> None:
    engine = DetectionEngine([_page(freq, min(freq + 600, 2900))])
    signal = concat(
        tone(freq * 1.035, 1.0, 0.5), silence(0.1), tone(min(freq + 600, 2900) * 1.035, 2.1, 0.5)
    )
    assert engine.feed(signal).detections == ()
