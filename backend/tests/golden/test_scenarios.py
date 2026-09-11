"""Golden M2 detection scenarios; audio is synthesized at test time."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from golden.scenarios import SCENARIOS, GoldenScenario
from tonewatch.config.models import ToneSet
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import (
    add_noise,
    clip,
    concat,
    phase_jump,
    pink_noise,
    silence,
    tone,
    voice_like,
)

if TYPE_CHECKING:
    import numpy as np


def _make_signal(scenario: GoldenScenario) -> np.ndarray:
    parts: list[np.ndarray] = []
    for kind, params in scenario.recipe:
        if kind == "tone":
            parts.append(tone(**params))
        elif kind == "silence":
            parts.append(silence(**params))
        elif kind == "voice":
            parts.append(voice_like(**params))
        elif kind == "pink":
            parts.append(pink_noise(**params))
        elif kind == "noise_page":
            page = concat(tone(1000, 1, 0.5), silence(0.1), tone(1500, 3, 0.5))
            parts.append(add_noise(page, **params))
        elif kind == "clip_page":
            parts.append(
                clip(concat(tone(1000, 1, 0.5), silence(0.1), tone(1500, 3, 0.5)), **params)
            )
        elif kind == "phase_page":
            parts.append(phase_jump(tone(1500, 3, 0.5), **params))
        else:
            raise AssertionError(f"unknown recipe step {kind}")
    return concat(*parts)


def _make_tonesets(scenario: GoldenScenario) -> list[ToneSet]:
    return [ToneSet.model_validate(item) for item in scenario.tonesets]


@pytest.mark.parametrize(
    "scenario",
    [scenario for scenario in SCENARIOS if not scenario.slow],
    ids=lambda item: item.name,
)
def test_golden_scenario(scenario: GoldenScenario) -> None:
    engine = DetectionEngine(_make_tonesets(scenario))
    detections = engine.feed(_make_signal(scenario)).detections
    actual = [(detection.toneset_id, detection.detected_at_s) for detection in detections]
    assert [item[0] for item in actual] == [item[0] for item in scenario.expected]
    for (_, actual_time), (_, expected_time) in zip(actual, scenario.expected, strict=True):
        assert actual_time == pytest.approx(expected_time, abs=0.3)


@pytest.mark.slow
def test_long_false_positive_scenarios() -> None:
    for scenario in (item for item in SCENARIOS if item.slow):
        engine = DetectionEngine(_make_tonesets(scenario))
        assert engine.feed(_make_signal(scenario)).detections == ()
    random_tonesets = [
        ToneSet.model_validate(
            {
                "id": f"random-{index}",
                "name": f"random-{index}",
                "sequence": [
                    {"freq_hz": 300 + ((index * 173) % 2600), "min_s": 0.5},
                ],
            }
        )
        for index in range(50)
    ]
    mixed_hour = concat(voice_like(1800, 40), pink_noise(1800, 0.2, 41))
    assert DetectionEngine(random_tonesets).feed(mixed_hour).detections == ()
