"""Data-only golden scenario definitions for M2.5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GoldenScenario:
    """A recipe, configuration, and expected early detections."""

    name: str
    recipe: tuple[tuple[str, dict[str, Any]], ...]
    tonesets: tuple[dict[str, Any], ...]
    expected: tuple[tuple[str, float], ...]
    slow: bool = False


def _page(
    first: float = 1000,
    second: float = 1500,
    first_dur: float = 1.0,
    second_dur: float = 3.0,
    gap: float = 0.1,
    *,
    toneset_id: str = "page",
    cooldown: float = 60,
) -> tuple[
    tuple[tuple[str, dict[str, Any]], ...],
    tuple[dict[str, Any], ...],
    tuple[tuple[str, float], ...],
]:
    return (
        (
            ("tone", {"freq_hz": first, "dur_s": first_dur, "amp": 0.5}),
            ("silence", {"dur_s": gap}),
            ("tone", {"freq_hz": second, "dur_s": second_dur, "amp": 0.5}),
        ),
        (
            {
                "id": toneset_id,
                "name": toneset_id,
                "sequence": [
                    {"freq_hz": first, "tol_pct": 1.5, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": second, "tol_pct": 1.5, "min_s": 2.0, "max_s": 3.5},
                ],
                "max_gap_s": 0.5,
                "cooldown_s": cooldown,
            },
        ),
        ((toneset_id, first_dur + gap + 2.0),),
    )


_clean_recipe, _clean_sets, _clean_expected = _page()

SCENARIOS: tuple[GoldenScenario, ...] = (
    GoldenScenario("clean_two_tone", _clean_recipe, _clean_sets, _clean_expected),
    GoldenScenario(
        "long_tone",
        (("tone", {"freq_hz": 1200, "dur_s": 8.0, "amp": 0.5}),),
        ({"id": "long", "name": "long", "sequence": [{"freq_hz": 1200, "min_s": 5, "max_s": 10}]},),
        (("long", 5.0),),
    ),
    *tuple(
        GoldenScenario(
            f"snr_{snr:g}db",
            (("noise_page", {"snr_db": snr, "seed": 3}),),
            _clean_sets,
            _clean_expected,
        )
        for snr in (20.0, 10.0, 6.0)
    ),
    GoldenScenario(
        "offset_1_4_percent",
        (
            ("tone", {"freq_hz": 1014, "dur_s": 1.0, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1521, "dur_s": 3.0, "amp": 0.5}),
        ),
        (
            {
                "id": "page",
                "name": "page",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1500, "min_s": 2.0, "max_s": 3.5},
                ],
            },
        ),
        (("page", 3.1),),
    ),
    GoldenScenario(
        "offset_3_5_percent_rejected",
        (
            ("tone", {"freq_hz": 1035, "dur_s": 1.0, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1552.5, "dur_s": 3.0, "amp": 0.5}),
        ),
        _clean_sets,
        (),
    ),
    GoldenScenario(
        "a_too_short",
        (
            ("tone", {"freq_hz": 1000, "dur_s": 0.48, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1500, "dur_s": 3.0, "amp": 0.5}),
        ),
        _clean_sets,
        (),
    ),
    GoldenScenario(
        "b_cutoff",
        (
            ("tone", {"freq_hz": 1000, "dur_s": 1.0, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1500, "dur_s": 1.0, "amp": 0.5}),
        ),
        _clean_sets,
        (),
    ),
    GoldenScenario("gap_0_3_ok", _page(gap=0.3)[0], _clean_sets, (("page", 3.3),)),
    GoldenScenario("gap_0_9_fail", _page(gap=0.9)[0], _clean_sets, ()),
    GoldenScenario(
        "shared_a",
        _page()[0],
        (
            {
                "id": "one",
                "name": "one",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1500, "min_s": 2, "max_s": 3.5},
                ],
            },
            {
                "id": "two",
                "name": "two",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1800, "min_s": 2, "max_s": 3.5},
                ],
            },
        ),
        (("one", 3.1),),
    ),
    GoldenScenario(
        "stacked_three",
        _page()[0]
        + _page(second=1800, toneset_id="second")[0]
        + _page(second=2200, toneset_id="third")[0],
        _clean_sets
        + (
            {
                "id": "second",
                "name": "second",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1800, "min_s": 2, "max_s": 3.5},
                ],
            },
            {
                "id": "third",
                "name": "third",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 2200, "min_s": 2, "max_s": 3.5},
                ],
            },
        ),
        (("page", 3.1), ("second", 7.2), ("third", 11.3)),
    ),
    GoldenScenario(
        "repeat_inside_cooldown", _page()[0] + _page()[0], _clean_sets, (("page", 3.1),)
    ),
    GoldenScenario(
        "repeat_after_cooldown",
        _page()[0] + (("silence", {"dur_s": 61.0}),) + _page()[0],
        ({**_clean_sets[0], "cooldown_s": 60},),
        (("page", 3.1), ("page", 68.2)),
    ),
    GoldenScenario(
        "voice_only_10m", (("voice", {"dur_s": 600.0, "seed": 4}),), _clean_sets, (), True
    ),
    GoldenScenario(
        "pink_noise_10m",
        (("pink", {"dur_s": 600.0, "amp": 0.2, "seed": 5}),),
        _clean_sets,
        (),
        True,
    ),
    GoldenScenario("clipped_0_3", (("clip_page", {"level": 0.3}),), _clean_sets, _clean_expected),
    GoldenScenario(
        "phase_jump",
        (
            ("tone", {"freq_hz": 1000, "dur_s": 1.0, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("phase_page", {"at_s": 1.0}),
        ),
        _clean_sets,
        _clean_expected,
    ),
    GoldenScenario(
        "adjacent_2_percent_right_set",
        _page(second=1530)[0],
        (
            {
                "id": "base",
                "name": "base",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1500, "min_s": 2, "max_s": 3.5},
                ],
            },
            {
                "id": "adjacent",
                "name": "adjacent",
                "sequence": [
                    {"freq_hz": 1000, "min_s": 0.8, "max_s": 1.4},
                    {"freq_hz": 1530, "min_s": 2, "max_s": 3.5},
                ],
            },
        ),
        (("adjacent", 3.1),),
    ),
    GoldenScenario(
        "tone_then_voice",
        _page()[0] + (("voice", {"dur_s": 2.0, "seed": 8}),),
        _clean_sets,
        _clean_expected,
    ),
    GoldenScenario("reverse_order_rejected", _page(first=1500, second=1000)[0], _clean_sets, ()),
    GoldenScenario("a_too_long", _page(first_dur=2.0)[0], _clean_sets, ()),
    GoldenScenario(
        "b_too_long_record_excess", _page(second_dur=5.0)[0], _clean_sets, _clean_expected
    ),
    GoldenScenario(
        "low_amplitude",
        (
            ("tone", {"freq_hz": 1000, "dur_s": 1.0, "amp": 0.1}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1500, "dur_s": 3.0, "amp": 0.1}),
        ),
        _clean_sets,
        _clean_expected,
    ),
    GoldenScenario(
        "only_a", (("tone", {"freq_hz": 1000, "dur_s": 1.0, "amp": 0.5}),), _clean_sets, ()
    ),
    GoldenScenario(
        "white_noise_20db",
        (("noise_page", {"snr_db": 20.0, "seed": 12}),),
        _clean_sets,
        _clean_expected,
    ),
    GoldenScenario(
        "jittered_durations",
        (
            ("tone", {"freq_hz": 1000, "dur_s": 0.95, "amp": 0.5}),
            ("silence", {"dur_s": 0.1}),
            ("tone", {"freq_hz": 1500, "dur_s": 2.2, "amp": 0.5}),
        ),
        _clean_sets,
        (("page", 3.25),),
    ),
)
