"""Tests for the legacy tones.cfg importer."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tonewatch.config.models import AppConfig, FileSource, MqttTarget, ToneSet, ToneSpec
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.generator import concat, silence, tone
from tonewatch.importers.tones_cfg import (
    TONES_CFG_MAX_BYTES,
    TONES_CFG_MAX_SECTIONS,
    TonesCfgImportLimitError,
    apply_tones_cfg,
    parse_tones_cfg,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tones_cfg" / "synthetic.cfg"


def test_synthetic_fixture_maps_sections_and_redacts_untrusted_fields() -> None:
    source = FIXTURE.read_text(encoding="utf-8-sig")
    result = parse_tones_cfg(source)
    crlf_result = parse_tones_cfg(source.replace("\n", "\r\n"))

    assert result.imported_count == 3
    assert result.skipped_count == 2
    assert crlf_result.to_json() == result.to_json()
    first, second = result.tone_sets[:2]
    assert first.id == "cedar-ridge-dispatch"
    assert first.sequence[0] == ToneSpec(freq_hz=853, tol_pct=2, min_s=0.6)
    assert first.sequence[1] == ToneSpec(freq_hz=960, tol_pct=2, min_s=1.2)
    assert first.record.post_s == 42
    assert first.cooldown_s == 17
    assert first.max_gap_s == 0.35
    assert second.id == "cedar-ridge-dispatch-2"
    assert second.sequence[0].tol_pct == 1.5
    assert any(
        "tone_tolerance missing" in note
        for section in result.sections
        if section.name == "LongBeacon"
        for note in section.notes
    )
    assert "email" in " ".join(result.notes).lower()
    assert "post_email_command" in " ".join(result.notes)
    assert "playback_during_record" in " ".join(result.notes)
    assert "release_time" in " ".join(result.notes)
    assert "send-alert" not in result.to_json()
    assert "@" not in result.to_json()
    assert any(section.errors for section in result.sections if section.name == "BadShape")


def test_apply_merge_deduplicates_and_replace_preserves_other_resources() -> None:
    result = parse_tones_cfg("[One]\nlongtone=1000\nlongtonelength=1\n")
    existing = AppConfig(
        tone_sets=[ToneSet(id="one", name="Old", sequence=[ToneSpec(freq_hz=500, min_s=1)])],
        sources=[FileSource(id="file", name="file", path="x.wav")],
        alert_targets=[MqttTarget(id="mqtt", name="mqtt")],
    )

    merged = apply_tones_cfg(existing, result, "merge")
    replaced = apply_tones_cfg(existing, result, "replace")
    assert [item.id for item in merged.tone_sets] == ["one", "one-2"]
    assert [item.id for item in replaced.tone_sets] == ["one"]
    assert replaced.sources == existing.sources
    assert replaced.alert_targets == existing.alert_targets


def test_imported_two_and_long_tones_detect_generated_audio() -> None:
    result = parse_tones_cfg(FIXTURE.read_text(encoding="utf-8-sig"))
    two_tone, long_tone = result.tone_sets[:2]

    # The analyzer needs one FFT window of settling audio around each edge.
    two_audio = concat(
        tone(two_tone.sequence[0].freq_hz, two_tone.sequence[0].min_s + 0.25, 0.5),
        silence(0.2),
        tone(two_tone.sequence[1].freq_hz, two_tone.sequence[1].min_s + 0.25, 0.5),
        silence(2),
    )
    long_audio = concat(
        tone(long_tone.sequence[0].freq_hz, long_tone.sequence[0].min_s + 0.25, 0.5),
        silence(2),
    )

    two_output = DetectionEngine([two_tone], window=800, hop=200).feed(two_audio)
    long_output = DetectionEngine([long_tone], window=800, hop=200).feed(long_audio)
    assert any(item.toneset_id == two_tone.id for item in two_output.detections), (
        two_output.segments
    )
    assert any(item.toneset_id == long_tone.id for item in long_output.detections), (
        long_output.segments
    )


def test_limits_are_typed_and_strict() -> None:
    with pytest.raises(TonesCfgImportLimitError):
        parse_tones_cfg("x" * (TONES_CFG_MAX_BYTES + 1))
    with pytest.raises(TonesCfgImportLimitError):
        parse_tones_cfg("\n".join(f"[S{i}]" for i in range(TONES_CFG_MAX_SECTIONS + 1)))


@given(st.text())
def test_arbitrary_text_never_raises_an_untyped_error(text: str) -> None:
    with suppress(TonesCfgImportLimitError):
        parse_tones_cfg(text)


def test_private_fixture_structural_properties_and_json_redaction() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    private = fixtures / "private" / "tones_cfg" / "tones.cfg"
    if not private.exists():
        pytest.skip("private tones.cfg fixture is not available")
    result = parse_tones_cfg(private.read_text(encoding="utf-8-sig"))
    assert result.tone_sets
    assert not any(section.errors for section in result.sections)
    assert all(250 <= tone.freq_hz <= 3000 for item in result.tone_sets for tone in item.sequence)
    assert all(tone.tol_pct == 2.0 for item in result.tone_sets for tone in item.sequence)
    assert "@" not in result.to_json()
    json.loads(result.to_json())


def test_tones_cfg_security_contract_is_documented() -> None:
    document = Path(__file__).parents[3] / "docs" / "security" / "threat-model" / "README.md"
    text = document.read_text(encoding="utf-8")
    assert "256 KiB" in text and "500 sections" in text
    assert "command fields are deliberately dropped" in text
    assert "Email fields are reduced to recipient counts" in text
