"""M13 discovery scenarios driven by the deterministic audio generator."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tonewatch.config.models import ToneSet
from tonewatch.dsp.discovery import DiscoveryTracker, ToneCandidate
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import Signal, add_noise, concat, silence, tone, voice_like


@dataclass(frozen=True)
class DiscoveryScenario:
    name: str
    signal: Signal
    tonesets: tuple[ToneSet, ...] = ()
    candidates: int = 1
    detections: int = 0


def _page(first: float = 1000, second: float = 1500) -> Signal:
    return concat(tone(first, 1, 0.5), silence(0.1), tone(second, 1, 0.5), silence(1))


def _known() -> ToneSet:
    return ToneSet.model_validate(
        {
            "id": "known-page",
            "name": "Known page",
            "sequence": [
                {"freq_hz": 1000, "min_s": 0.5},
                {"freq_hz": 1500, "min_s": 0.5},
            ],
        }
    )


def _disabled_known() -> ToneSet:
    return _known().model_copy(update={"enabled": False})


def _run(signal: Signal, tonesets: tuple[ToneSet, ...] = ()) -> tuple[list[ToneCandidate], int]:
    engine = DetectionEngine(list(tonesets))
    output = engine.feed(signal)
    tracker = DiscoveryTracker(known_tonesets=tonesets)
    candidates = tracker.feed(output.segment_update, output.detections, signal.size / 16_000)
    return candidates, len(output.detections)


@pytest.mark.parametrize(
    "scenario",
    [
        DiscoveryScenario("unknown two-tone", _page()),
        DiscoveryScenario("known page", _page(), (_known(),), candidates=0, detections=1),
        DiscoveryScenario(
            "known page repeated inside cooldown",
            concat(_page(), _page()),
            (_known(),),
            candidates=0,
            detections=1,
        ),
        DiscoveryScenario(
            "disabled known page",
            _page(),
            (_disabled_known(),),
            candidates=0,
            detections=0,
        ),
        DiscoveryScenario(
            "known then unknown inside cooldown",
            concat(_page(), _page(1800, 2200)),
            (_known(),),
            candidates=1,
            detections=1,
        ),
        DiscoveryScenario(
            "jittered repeats",
            concat(_page(1000 * 1.005, 1500 * 0.995), _page(1000 * 0.997, 1500 * 1.004), _page()),
            candidates=3,
        ),
        DiscoveryScenario(
            "separate clusters",
            concat(_page(), _page(1040, 1560)),
            candidates=2,
        ),
        DiscoveryScenario(
            "stacked known and unknown",
            concat(_page(), _page(1800, 2200)),
            (_known(),),
            candidates=1,
            detections=1,
        ),
        DiscoveryScenario("unknown long tone", concat(tone(1800, 4, 0.5), silence(1))),
        DiscoveryScenario("short blip", concat(tone(1800, 0.15, 0.5), silence(1)), candidates=0),
        DiscoveryScenario(
            "noisy unknown page", add_noise(_page(), snr_db=10, seed=13), candidates=1
        ),
    ],
    ids=lambda scenario: scenario.name,
)
def test_discovery_scenario(scenario: DiscoveryScenario) -> None:
    candidates, detections = _run(scenario.signal, scenario.tonesets)
    assert len(candidates) == scenario.candidates
    assert detections == scenario.detections


def test_ten_minute_voice_has_no_discovery_candidates() -> None:
    candidates, detections = _run(voice_like(600, seed=71))
    assert candidates == []
    assert detections == 0
