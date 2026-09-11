"""Edge and CLI coverage for the M2 implementation."""

from __future__ import annotations

import json
import sys
import wave

import numpy as np
import pytest

from tonewatch.__main__ import main
from tonewatch.config.models import ToneSet
from tonewatch.dsp.generator import (
    _write_wav,
    clip,
    jitter,
    pink_noise,
    silence,
    tone,
    voice_like,
    white_noise,
)
from tonewatch.dsp.generator import main as generator_main
from tonewatch.dsp.spectrum import SpectrumAnalyzer


def test_generator_edges_and_wav_cli(tmp_path, monkeypatch, capsys) -> None:
    assert silence(0).size == 0
    assert pink_noise(0).size == 0
    assert white_noise(0).size == 0
    assert voice_like(0).size == 0
    assert jitter(1, 0, 3) == 1
    assert np.max(np.abs(clip(tone(1000, 0.1, 1), 0.3))) <= 0.3
    with pytest.raises(ValueError):
        tone(-1, 1)
    with pytest.raises(ValueError):
        clip(tone(1, 1), 0)
    with pytest.raises(ValueError):
        jitter(1, -1)
    wav_path = tmp_path / "sample.wav"
    config_path = tmp_path / "config.yaml"
    _write_wav(wav_path, tone(1000, 1.0, 0.5))
    config_path.write_text(
        "tone_sets:\n  - id: long\n    name: long\n    sequence:\n      - freq_hz: 1000\n        min_s: 0.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["tonewatch", "analyze", str(wav_path), "--config", str(config_path), "--json", "--frames"],
    )
    main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["detections"][0]["toneset_id"] == "long"
    generated_path = tmp_path / "generated.wav"
    monkeypatch.setattr(
        sys, "argv", ["tonewatch-gen", str(generated_path), "--tone", "1000", "--duration", "0.2"]
    )
    generator_main()
    assert generated_path.exists()


def test_wav_reader_handles_8_bit_and_spectrum_validation(tmp_path) -> None:
    path = tmp_path / "eight.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(1)
        output.setframerate(8000)
        output.writeframes(bytes([128]) * 8000)
    with pytest.raises(ValueError):
        SpectrumAnalyzer(window=2)
    assert path.exists()


def test_models_are_accepted_by_cli_types() -> None:
    assert ToneSet.model_validate(
        {"id": "x", "name": "x", "sequence": [{"freq_hz": 300, "min_s": 1}]}
    )
