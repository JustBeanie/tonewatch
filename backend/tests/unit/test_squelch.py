"""Software squelch behavior."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from tonewatch.config.models import RtlSdrSource, SoundcardSource
from tonewatch.dsp.generator import add_noise, concat, voice_like, white_noise
from tonewatch.dsp.squelch import Squelch, SquelchConfig
from tonewatch.events import ChannelLevel


def test_level_hysteresis_attack_and_hang() -> None:
    squelch = Squelch(
        SquelchConfig(mode="level", open_dbfs=-40, close_dbfs=-45, attack_ms=100, hang_ms=200)
    )
    assert squelch.feed(-39, 0) == (False, False)
    assert squelch.feed(-39, 0.1) == (True, True)
    assert squelch.feed(-46, 0.2) == (True, False)
    assert squelch.feed(-46, 0.4) == (False, True)


def test_between_thresholds_never_transitions() -> None:
    squelch = Squelch(SquelchConfig(mode="level", attack_ms=0, hang_ms=0))
    assert all(not squelch.feed(-42, n / 10)[1] for n in range(100))


@given(level=st.floats(min_value=-44.9, max_value=-40.1, allow_nan=False))
def test_hypothesis_between_thresholds_never_transitions(level: float) -> None:
    squelch = Squelch(
        SquelchConfig(mode="level", open_dbfs=-40, close_dbfs=-45, attack_ms=0, hang_ms=0)
    )
    assert not squelch.feed(level, 0)[1]


@given(
    levels=st.lists(
        st.floats(min_value=-44.9, max_value=-40.1, allow_nan=False), min_size=1, max_size=100
    )
)
def test_hypothesis_noise_has_at_most_one_transition_per_hang_window(
    levels: list[float],
) -> None:
    squelch = Squelch(SquelchConfig(mode="level", attack_ms=0, hang_ms=1))
    transitions = [squelch.feed(level, index * 0.1)[1] for index, level in enumerate(levels)]
    assert sum(transitions) <= max(1, len(levels) // 10 + 1)


@given(
    levels=st.lists(
        st.floats(min_value=-100, max_value=-1, allow_nan=False), min_size=1, max_size=100
    )
)
def test_hypothesis_noise_floor_open_threshold_respects_margin(levels: list[float]) -> None:
    squelch = Squelch(SquelchConfig(mode="noise_floor"))
    for index, level in enumerate(levels):
        squelch.feed(level, index * 0.1)
        if squelch.noise_floor is not None:
            assert squelch.open_threshold_dbfs >= squelch.noise_floor + 10


def test_noise_floor_tracks_quiet_levels() -> None:
    squelch = Squelch(SquelchConfig(mode="noise_floor", floor_margin_db=10, attack_ms=0, hang_ms=0))
    for n in range(20):
        squelch.feed(-70, float(n))
    assert squelch.noise_floor == pytest.approx(-70)
    assert squelch.feed(-59, 20)[0]


def test_config_validates_ranges_and_order() -> None:
    with pytest.raises(ValidationError):
        SquelchConfig(close_dbfs=-30, open_dbfs=-40)
    with pytest.raises(ValidationError):
        SquelchConfig(floor_margin_db=0)


def test_rtlsdr_dict_squelch_is_preserved_and_legacy_int_migrates() -> None:
    configured = RtlSdrSource.model_validate(
        {"id": "rtl", "name": "RTL", "freq_hz": 154000000, "squelch": {"mode": "level"}}
    )
    assert configured.squelch.mode == "level"
    legacy = RtlSdrSource.model_validate(
        {"id": "rtl", "name": "RTL", "freq_hz": 154000000, "squelch": 7}
    )
    assert legacy.rtl_fm_squelch == 7


def test_non_rtlsdr_integer_squelch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="valid dictionary"):
        SoundcardSource.model_validate(
            {"id": "card", "name": "Card", "device": "default", "squelch": 7}
        )


def test_boolean_legacy_squelch_is_not_migrated() -> None:
    with pytest.raises(ValidationError, match="valid dictionary"):
        RtlSdrSource.model_validate(
            {"id": "rtl", "name": "RTL", "freq_hz": 154000000, "squelch": True}
        )


def test_channel_level_keeps_rms_and_has_optional_squelch_level() -> None:
    level = ChannelLevel("source", -20.0, 0.5, __import__("datetime").datetime.now(), None, -35.0)
    assert level.rms_dbfs == -20.0
    assert level.squelch_level_dbfs == -35.0


def test_golden_voice_like_noise_bursts_have_one_open_close_pair_each() -> None:
    burst = add_noise(voice_like(0.6, seed=11), snr_db=15, seed=12)
    signal = concat(
        white_noise(1.0, amp=0.01, seed=1),
        burst,
        white_noise(0.8, amp=0.01, seed=2),
        add_noise(voice_like(0.6, seed=13), snr_db=15, seed=14),
        white_noise(1.0, amp=0.01, seed=3),
    )
    squelch = Squelch(
        SquelchConfig(mode="level", open_dbfs=-20, close_dbfs=-26, attack_ms=0, hang_ms=200)
    )
    transitions: list[tuple[float, bool]] = []
    for index in range(signal.size // 1600):
        samples = signal[index * 1600 : (index + 1) * 1600]
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        level = 20 * np.log10(max(rms, 1e-12))
        state, changed = squelch.feed(float(level), (index + 1) * 0.1)
        if changed:
            transitions.append(((index + 1) * 0.1, state))
    assert [state for _time, state in transitions] == [True, False, True, False]
    assert transitions[0][0] <= 1.0 + 0.6 + 0.3
    assert transitions[1][0] >= 1.0 + 0.6
    assert transitions[2][0] <= 1.0 + 0.6 + 0.8 + 0.6 + 0.3
    assert transitions[3][0] >= 1.0 + 0.6 + 0.8 + 0.6
