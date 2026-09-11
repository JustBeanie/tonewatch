"""Tests for the evidence-bound S1 scorecard tool."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from _pytest.fixtures import FixtureRequest

SCRIPT = Path(__file__).parents[3] / "scripts/security_scorecard.py"
SPEC = importlib.util.spec_from_file_location("security_scorecard", SCRIPT)
assert SPEC and SPEC.loader
scorecard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scorecard
SPEC.loader.exec_module(scorecard)


def _entries() -> list[dict[str, Any]]:
    result = []
    for function, practices in scorecard.SAMM_FUNCTIONS.items():
        for practice in practices:
            for stream in ("A", "B"):
                na = practice in {"Education & Guidance", "Incident Management"}
                stream_name = f"Stream {stream}"
                result.append(
                    {
                        "function": function,
                        "practice": practice,
                        "stream": stream_name,
                        "stream_id": f"TEST-{stream}",
                        "current_level": 0,
                        "target_level": scorecard.SAMM_TARGETS.get(practice, 1),
                        "answers": [
                            {
                                "level": level,
                                "question": f"Q{level}",
                                "answer": "No",
                                "rationale": "fixture",
                            }
                            for level in (1, 2, 3)
                        ],
                        "evidence": [],
                        "na": na,
                        "na_justification": "Not applicable to a solo project." if na else None,
                        "assessed_on": "2026-09-10",
                    }
                )
    return result


def _write_fixture(root: Path, entries: list[dict[str, Any]] | None = None) -> None:
    (root / "docs/security/samm").mkdir(parents=True)
    (root / "docs/security/dsomm").mkdir(parents=True)
    (root / "docs/security/samm/assessment.yaml").write_text(
        yaml.safe_dump({"entries": entries or _entries()}, sort_keys=False), encoding="utf-8"
    )
    activity = {
        "activities": [
            {
                "id": "a",
                "name": "Activity",
                "dimension": "Build & Deployment",
                "subdimension": "Build",
                "level": 1,
                "status": "planned",
                "evidence": [],
                "planned_in": "S2",
                "notes": "future",
            }
        ]
    }
    (root / "docs/security/dsomm/activities.yaml").write_text(
        yaml.safe_dump(activity, sort_keys=False), encoding="utf-8"
    )


def _official_fixture(
    entries: list[dict[str, Any]],
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    result = {}
    for entry in entries:
        for answer in entry["answers"]:
            result[(entry["function"], entry["practice"], entry["stream"], answer["level"])] = {
                "question": answer["question"],
                "answer_options": ["No", "Yes"],
            }
    return result


@pytest.fixture
def fixture_root(request: FixtureRequest) -> Path:
    root = Path.cwd() / ".tmp-security-scorecard"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir()
    request.addfinalizer(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def test_valid_fixture_passes(fixture_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_fixture(fixture_root)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: _official_fixture(_entries()))
    samm, dsomm = scorecard.validate()
    assert len(samm) == 30
    assert len(dsomm) == 1


def test_missing_evidence_fails(fixture_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = _entries()
    entries[0]["current_level"] = 0.5
    _write_fixture(fixture_root, entries)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: _official_fixture(entries))
    with pytest.raises(ValueError, match="no evidence"):
        scorecard.validate()


def test_nonexistent_evidence_path_fails(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = _entries()
    entries[0]["evidence"] = ["missing.txt"]
    _write_fixture(fixture_root, entries)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: _official_fixture(entries))
    with pytest.raises(ValueError, match="does not exist"):
        scorecard.validate()


def test_non_official_question_fails(fixture_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = _entries()
    official = _official_fixture(entries)
    entries[0]["answers"][0]["question"] = "Invented question"
    _write_fixture(fixture_root, entries)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: official)
    with pytest.raises(ValueError, match="question does not match"):
        scorecard.validate()


def test_na_without_justification_fails(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = _entries()
    entries[4]["na_justification"] = None
    entries[4]["current_level"] = 0
    _write_fixture(fixture_root, entries)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: _official_fixture(entries))
    with pytest.raises(ValueError, match="N/A"):
        scorecard.validate()


def test_generated_markdown_is_deterministic(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_fixture(fixture_root)
    monkeypatch.setattr(scorecard, "ROOT", fixture_root)
    monkeypatch.setattr(scorecard, "_official_questions", lambda: _official_fixture(_entries()))
    samm, dsomm = scorecard.validate()
    first = scorecard.render(samm, dsomm)
    second = scorecard.render(samm, dsomm)
    assert first == second
