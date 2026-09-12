"""M2.6 benchmark: 200 tone sets over ten minutes of realistic audio.

The signal interleaves voice-like audio and pink noise with a real two-tone page
every 30 seconds, so the segmenter and matcher do actual work instead of idling on
non-tonal frames. Each round builds a fresh engine so rounds are independent.
"""

from __future__ import annotations

from tonewatch.config.models import ToneSet
from tonewatch.dsp.discovery import DiscoveryTracker
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import Signal, concat, pink_noise, silence, tone, voice_like

PAGE_A_HZ = 1000.0
PAGE_B_HZ = 1500.0
PAGES = 20  # one per 30 s block -> 600 s of audio


def _two_tone(toneset_id: str, first_hz: float, second_hz: float) -> ToneSet:
    return ToneSet.model_validate(
        {
            "id": toneset_id,
            "name": toneset_id,
            "sequence": [
                {"freq_hz": first_hz, "min_s": 0.8, "max_s": 1.4},
                {"freq_hz": second_hz, "min_s": 2.0, "max_s": 3.5},
            ],
            "cooldown_s": 5,
        }
    )


def _tonesets() -> list[ToneSet]:
    # 199 decoy two-tone sets spread across the band (none share both tones with
    # the page) plus the one set that actually fires.
    decoys = [_two_tone(f"set-{i}", 300 + i * 12, 320 + i * 13) for i in range(199)]
    return [*decoys, _two_tone("page", PAGE_A_HZ, PAGE_B_HZ)]


def _signal() -> Signal:
    blocks: list[Signal] = []
    for index in range(PAGES):
        blocks += [
            tone(PAGE_A_HZ, 1.0, 0.5),
            silence(0.1),
            tone(PAGE_B_HZ, 3.0, 0.5),
            voice_like(12.9, seed=100 + index),
            pink_noise(13.0, 0.2, seed=200 + index),
        ]
    return concat(*blocks)


def test_detection_engine_realtime(benchmark) -> None:
    tonesets = _tonesets()
    signal = _signal()

    def run() -> list[str]:
        output = DetectionEngine(tonesets).feed(signal)
        tracker = DiscoveryTracker()
        tracker.feed(output.segment_update, output.detections, 600.0)
        return [detection.toneset_id for detection in output.detections]

    detected = benchmark(run)
    assert detected == ["page"] * PAGES
