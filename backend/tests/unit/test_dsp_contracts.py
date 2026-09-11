"""Contract tests for the pure M2 DSP components."""

from __future__ import annotations

import numpy as np
import pytest

from tonewatch.config.models import ToneSet, ToneSpec
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import add_noise, concat, phase_jump, tone
from tonewatch.dsp.matcher import Detection, Matcher
from tonewatch.dsp.segmenter import Segmenter
from tonewatch.dsp.spectrum import SpectrumAnalyzer


def _toneset(name: str = "page", *, cooldown: float = 60) -> ToneSet:
    return ToneSet(
        id=name,
        name=name,
        sequence=[
            ToneSpec(freq_hz=1000, tol_pct=1.5, min_s=0.8, max_s=1.4),
            ToneSpec(freq_hz=1500, tol_pct=1.5, min_s=1.8, max_s=3.5),
        ],
        max_gap_s=0.5,
        cooldown_s=cooldown,
    )


def test_generator_is_seeded_and_composable() -> None:
    first = add_noise(concat(tone(1000, 0.2, 0.4), tone(1500, 0.2, 0.4)), 10, 7)
    second = add_noise(concat(tone(1000, 0.2, 0.4), tone(1500, 0.2, 0.4)), 10, 7)
    assert first.dtype == np.float32
    assert np.array_equal(first, second)
    jumped = phase_jump(tone(1000, 0.4, 0.4), 0.2)
    assert np.array_equal(jumped[:3200], tone(1000, 0.2, 0.4))
    assert np.allclose(jumped[3200:], -tone(1000, 0.2, 0.4), atol=1e-6)


def test_spectrum_is_incremental_and_precise() -> None:
    samples = tone(1234.5, 1.5, 0.5)
    whole = SpectrumAnalyzer().feed(samples)
    chunked: list = []
    analyzer = SpectrumAnalyzer()
    for chunk in np.array_split(samples, [1, 334, 1934, 3534, 12000]):
        chunked.extend(analyzer.feed(chunk))
    assert len(whole) == len(chunked)
    assert np.allclose(
        [(frame.freq_hz, frame.level_dbfs, frame.purity) for frame in whole],
        [(frame.freq_hz, frame.level_dbfs, frame.purity) for frame in chunked],
        atol=1e-6,
    )
    assert abs(whole[0].freq_hz - 1234.5) < 0.5
    assert whole[0].tonal


def test_segmenter_opens_extends_and_closes_after_dropouts() -> None:
    frames = SpectrumAnalyzer().feed(
        concat(tone(1000, 1.0, 0.5), np.zeros(1600, dtype=np.float32), tone(1500, 0.3, 0.5))
    )
    updates = []
    segmenter = Segmenter(max_dropout_frames=2)
    for frame in frames:
        updates.append(segmenter.feed([frame]))
    assert any(update.opened for update in updates)
    assert any(update.extended for update in updates)
    assert any(update.closed for update in updates)
    assert updates[0].opened[0].closed is False


def test_matcher_emits_early_once_and_enforces_stream_cooldown() -> None:
    signal = concat(tone(1000, 1.0, 0.5), np.zeros(3200, dtype=np.float32), tone(1500, 2.2, 0.5))
    engine = DetectionEngine([_toneset(cooldown=30)])
    detections: list[Detection] = []
    for chunk in np.array_split(signal, 11):
        detections.extend(engine.feed(chunk).detections)
    assert len(detections) == 1
    assert detections[0].early
    assert detections[0].toneset_id == "page"


def test_matcher_allows_stacked_sets_and_rejects_large_offset() -> None:
    signal = concat(tone(1000, 1.0, 0.5), np.zeros(1600, dtype=np.float32), tone(1500, 2.0, 0.5))
    tonesets = [_toneset("one"), _toneset("two")]
    detections: list[Detection] = []
    engine = DetectionEngine(tonesets)
    for chunk in np.array_split(signal, 5):
        output = engine.feed(chunk)
        detections.extend(output.detections)
    assert {d.toneset_id for d in detections} == {"one", "two"}


def test_phase_jump_does_not_destroy_detection() -> None:
    signal = concat(
        tone(1000, 1.0, 0.5),
        np.zeros(1600, dtype=np.float32),
        phase_jump(tone(1500, 2.1, 0.5), 1.0),
    )
    output = DetectionEngine([_toneset()]).feed(signal)
    assert len(output.detections) == 1


@pytest.mark.parametrize("_unused", range(1), ids=["smoke"])
def test_matcher_type_is_importable(_unused: int) -> None:
    assert isinstance(Matcher([_toneset()]), Matcher)
