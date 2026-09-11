"""M1.1 domain model tests."""

import pytest
from pydantic import ValidationError

from tonewatch.config.models import AppConfig, FileSource, ToneSet, ToneSpec


def tone(freq: float = 1000) -> ToneSpec:
    return ToneSpec(freq_hz=freq, min_s=1)


def test_constraints_and_adjacent_overlap_are_linted() -> None:
    config = AppConfig(tone_sets=[ToneSet(id="page", name="Page", sequence=[tone(), tone(1010)])])
    assert config.lint()
    assert config.tone_sets[0].record.formats == ["mp3"]
    with pytest.raises(ValidationError):
        ToneSpec(freq_hz=100, min_s=1)


def test_discriminated_source_and_cross_references() -> None:
    config = AppConfig.model_validate(
        {
            "sources": [
                {
                    "type": "file",
                    "id": "scanner",
                    "name": "Scanner",
                    "path": "a.wav",
                    "tonesets": ["page"],
                }
            ],
            "tone_sets": [
                {"id": "page", "name": "Page", "sequence": [{"freq_hz": 1000, "min_s": 1}]}
            ],
        }
    )
    assert isinstance(config.sources[0], FileSource)
    with pytest.raises(ValidationError, match="missing tone set absent"):
        AppConfig.model_validate(
            {
                "sources": [
                    {
                        "type": "file",
                        "id": "scanner",
                        "name": "Scanner",
                        "path": "a.wav",
                        "tonesets": ["absent"],
                    }
                ]
            }
        )
