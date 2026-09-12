"""Machine checks for the pinned ASVS L1/L2 evidence ledger."""

import ast
import csv
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[3]
SOURCE = (
    ROOT / "docs/security/asvs/source/OWASP_Application_Security_Verification_Standard_5.0.0_en.csv"
)
CHECKLIST = ROOT / "docs/security/asvs/checklist.csv"
GAPS = ROOT / "docs/security/gaps.md"
ACCEPTED = ROOT / "docs/security/accepted-risks.md"


def _tests() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "backend/tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return names


def _source_rows() -> list[dict[str, str]]:
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["L"] in {"1", "2"}]


def _checklist_rows() -> list[dict[str, str]]:
    with CHECKLIST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    # An unquoted comma spills cells under a None key and silently truncates notes.
    assert all(None not in row for row in rows), [row["id"] for row in rows if None in row]
    return rows


def _evidence_parts(value: str) -> tuple[Path, int] | None:
    match = re.fullmatch(r"(.+):([0-9]+)", value)
    if match is None:
        return None
    return ROOT / match[1], int(match[2])


def _accepted_risks() -> dict[str, date]:
    text = ACCEPTED.read_text(encoding="utf-8")
    risks: dict[str, date] = {}
    sections = re.finditer(r"^## (AR-\d{3})\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    for section in sections:
        expiry = re.search(r"^- Expires:\s*(\d{4}-\d{2}-\d{2})\s*$", section.group(0), re.MULTILINE)
        if expiry is not None:
            risks[section.group(1)] = date.fromisoformat(expiry.group(1))
    return risks


def test_asvs_checklist_covers_pinned_l1_l2_requirements() -> None:
    source = _source_rows()
    rows = _checklist_rows()
    ids = [row["id"] for row in rows]
    assert set(ids) == {row["req_id"] for row in source}
    assert len(ids) == len(set(ids)) == len(source)
    source_levels = {row["req_id"]: row["L"] for row in source}
    assert all(row["level"] == source_levels[row["id"]] for row in rows)
    assert all(row["status"] in {"pass", "fixed", "na", "accepted", "gap"} for row in rows)
    assert not any(row["status"] == "fail" for row in rows)


def test_asvs_evidence_is_specific_and_referential() -> None:
    rows = _checklist_rows()
    tests = _tests()
    evidence_counts = Counter(
        row["evidence (path:line)"] for row in rows if row["evidence (path:line)"]
    )
    test_counts = Counter(
        row["test (function name)"] for row in rows if row["test (function name)"]
    )
    assert all(count <= 8 for count in evidence_counts.values())
    assert all(count <= 8 for count in test_counts.values())
    for row in rows:
        if row["status"] not in {"pass", "fixed", "accepted"}:
            continue
        evidence = _evidence_parts(row["evidence (path:line)"])
        assert evidence is not None, row["id"]
        path, line = evidence
        assert path.relative_to(ROOT).as_posix().startswith(("backend/src/", "docs/")), row["id"]
        assert path.is_file(), row["id"]
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= line, row["id"]
        assert lines[line - 1].strip(), row["id"]
        if row["test (function name)"] != "doc-only":
            assert row["test (function name)"] in tests, row["id"]


def test_asvs_notes_and_documentation_rows_are_bounded() -> None:
    rows = _checklist_rows()
    assert all(len(row["notes"].strip()) >= 40 for row in rows)
    assert all(count <= 2 for count in Counter(row["notes"] for row in rows).values())
    doc_only = [row for row in rows if row["test (function name)"] == "doc-only"]
    assert len(doc_only) <= 40
    assert all(row["evidence (path:line)"].startswith("docs/") for row in doc_only)
    for row in rows:
        if row["status"] == "na":
            assert row["applicable"] == "no"
            assert "not applicable" in row["notes"]


def test_asvs_feature_specific_requirements_are_not_keyword_matched() -> None:
    """Keep controls for absent protocols from inheriting unrelated evidence."""
    feature_requirements = re.compile(
        r"\b(oauth|authorization code|refresh token|turn|webrtc|dtls|jwt|self-contained token)\b",
        re.IGNORECASE,
    )
    for row in _checklist_rows():
        if not feature_requirements.search(row["requirement (verbatim)"]):
            continue
        explicitly_justified = "applicability justified:" in row["notes"].lower()
        assert row["status"] == "na" or explicitly_justified, row["id"]


def test_asvs_header_evidence_names_the_enforced_header() -> None:
    """A browser-header requirement needs evidence of that exact header."""
    headers = (
        "strict-transport-security",
        "content-security-policy",
        "x-content-type-options",
        "referrer-policy",
        "frame-ancestors",
    )
    for row in _checklist_rows():
        if row["status"] not in {"pass", "fixed"}:
            continue
        required = [header for header in headers if header in row["requirement (verbatim)"].lower()]
        if not required:
            continue
        evidence = _evidence_parts(row["evidence (path:line)"])
        assert evidence is not None, row["id"]
        path, line = evidence
        source_line = path.read_text(encoding="utf-8").splitlines()[line - 1].lower()
        assert all(header in source_line for header in required), row["id"]


def test_asvs_notes_are_not_templated() -> None:
    rows = _checklist_rows()
    forbidden = "the cited test exercises this exact control"
    assert all(forbidden not in row["notes"].lower() for row in rows)
    sentences = [
        sentence.strip()
        for row in rows
        for sentence in re.split(r"(?<=[.!?])\s+", row["notes"])
        if sentence.strip()
    ]
    assert all(count <= 2 for count in Counter(sentences).values())


def test_asvs_gaps_name_existing_targeted_register_entries() -> None:
    rows = _checklist_rows()
    gap_text = GAPS.read_text(encoding="utf-8")
    targets = {"S5", "S6", "M9", "M10", "M11", "M12"}
    for row in rows:
        if row["status"] != "gap":
            continue
        match = re.search(r"\b(GAP-\d{3})\b", row["notes"])
        assert match is not None, row["id"]
        start = gap_text.find(f"## {match.group(1)} ")
        assert start >= 0, row["id"]
        next_heading = gap_text.find("\n## ", start + 1)
        section = gap_text[start : next_heading if next_heading >= 0 else len(gap_text)]
        assert row["id"] in section
        assert "Requirement:" in section and "Why unmet:" in section
        assert any(f"Target milestone: {target}" in section for target in targets)


def test_asvs_accepted_rows_name_current_short_lived_risks() -> None:
    rows = _checklist_rows()
    risks = _accepted_risks()
    today = datetime.now(UTC).date()
    for row in rows:
        if row["status"] != "accepted":
            continue
        ids = re.findall(r"\bAR-\d{3}\b", row["notes"])
        assert ids and all(risk_id in risks for risk_id in ids), row["id"]
        assert all(today < risks[risk_id] <= today + timedelta(days=90) for risk_id in ids)
