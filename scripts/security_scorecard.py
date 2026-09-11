"""Validate and render the S1 security maturity scorecards."""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-10"
SAMM_TARGETS = {
    "Threat Assessment": 2,
    "Security Requirements": 2,
    "Secure Build": 2,
    "Secure Deployment": 2,
    "Defect Management": 2,
    "Security Testing": 2,
}
SAMM_FUNCTIONS = {
    "Governance": ["Strategy & Metrics", "Policy & Compliance", "Education & Guidance"],
    "Design": ["Threat Assessment", "Security Requirements", "Secure Architecture"],
    "Implementation": ["Secure Build", "Secure Deployment", "Defect Management"],
    "Verification": [
        "Architecture Assessment",
        "Requirements-driven Testing",
        "Security Testing",
    ],
    "Operations": [
        "Incident Management",
        "Environment Management",
        "Operational Management",
    ],
}
OWNER_ORDER = [
    "M0",
    "M1",
    "S1",
    "S2",
    "M2",
    "M3",
    "M4",
    "M5",
    "S3",
    "M6",
    "M7",
    "S4",
    "M8",
    "S5",
    "M9",
    "M10",
    "M11",
    "S6",
    "S7",
    "M12",
]
ModelT = TypeVar("ModelT", bound=BaseModel)


class Answer(BaseModel):
    level: int = Field(ge=1, le=3)
    question: str
    answer: str
    rationale: str


class SammEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function: str
    practice: str
    stream: str
    stream_id: str
    current_level: float = Field(ge=0, le=3)
    target_level: float = Field(ge=0, le=3)
    answers: list[Answer] = Field(min_length=1)
    evidence: list[str]
    na: bool = False
    na_justification: str | None = None
    assessed_on: str

    @field_validator("assessed_on", mode="before")
    @classmethod
    def date_as_text(cls, value: Any) -> str:
        return str(value)

    @field_validator("current_level", "target_level")
    @classmethod
    def half_steps(cls, value: float) -> float:
        if not math.isclose(value * 2, round(value * 2)):
            raise ValueError("SAMM levels must use 0.5 steps")
        return value


class DsommActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    dimension: str
    subdimension: str
    level: int = Field(ge=1, le=2)
    status: str
    evidence: list[str]
    planned_in: str
    notes: str

    @field_validator("status")
    @classmethod
    def status_value(cls, value: str) -> str:
        if value not in {"implemented", "partial", "planned", "na"}:
            raise ValueError("invalid DSOMM status")
        return value


def _load(path: Path, model: type[ModelT]) -> list[ModelT]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = raw.get("entries", raw.get("activities", raw))
    if not isinstance(items, list):
        raise TypeError(f"{path} must contain a list")
    return [model.model_validate(item) for item in items]


def _evidence_ok(value: str) -> bool:
    return bool(re.match(r"^https?://", value)) or (ROOT / value).exists()


def _official_questions() -> dict[tuple[str, str, str, int], dict[str, Any]]:
    raw = yaml.safe_load(
        (ROOT / "docs/security/samm/model/questions.yaml").read_text(encoding="utf-8")
    )
    return {
        (item["function"], item["practice"], item["stream_name"], item["level"]): item
        for item in raw["questions"]
    }


def validate() -> tuple[list[SammEntry], list[DsommActivity]]:
    samm = [x for x in _load(ROOT / "docs/security/samm/assessment.yaml", SammEntry)]
    dsomm = [
        x for x in _load(ROOT / "docs/security/dsomm/activities.yaml", DsommActivity)
    ]
    official = _official_questions()
    if len(samm) != 30:
        raise ValueError(f"SAMM requires 30 practice/stream entries, got {len(samm)}")
    seen = set()
    for entry in samm:
        key = (entry.function, entry.practice, entry.stream)
        if key in seen:
            raise ValueError(f"duplicate SAMM entry: {key}")
        seen.add(key)
        minimum = SAMM_TARGETS.get(entry.practice, 1)
        if entry.target_level < minimum:
            raise ValueError(f"target below PLAN target for {entry.practice}")
        if entry.current_level > 0 and not entry.evidence:
            raise ValueError(f"claimed SAMM level has no evidence: {key}")
        if entry.na_justification is not None and not entry.na_justification.strip():
            raise ValueError(f"empty N/A justification: {key}")
        if entry.na and not entry.na_justification:
            raise ValueError(f"N/A entry lacks justification: {key}")
        if entry.na and entry.current_level != 0:
            raise ValueError(f"N/A entry must have level zero: {key}")
        for answer in entry.answers:
            official_key = (entry.function, entry.practice, entry.stream, answer.level)
            model = official.get(official_key)
            if model is None:
                raise ValueError(f"entry is not in pinned SAMM model: {official_key}")
            if answer.question != model["question"]:
                raise ValueError(
                    f"question does not match pinned SAMM model: {official_key}"
                )
            if answer.answer not in model["answer_options"]:
                raise ValueError(f"answer is not an official option: {official_key}")
        for evidence in entry.evidence:
            if not _evidence_ok(evidence):
                raise ValueError(f"evidence path does not exist: {evidence}")
    for ds_entry in dsomm:
        if ds_entry.status == "implemented" and not ds_entry.evidence:
            raise ValueError(
                f"implemented DSOMM activity has no evidence: {ds_entry.id}"
            )
        for evidence in ds_entry.evidence:
            if not _evidence_ok(evidence):
                raise ValueError(f"evidence path does not exist: {evidence}")
    return samm, dsomm


def _owner_key(value: str) -> tuple[int, str]:
    match = re.search(r"(?:M|S)\d+", value)
    token = match.group(0) if match else "M12"
    return (
        OWNER_ORDER.index(token) if token in OWNER_ORDER else len(OWNER_ORDER),
        value,
    )


def render(samm: list[SammEntry], dsomm: list[DsommActivity]) -> dict[Path, str]:
    lines = [
        "# SAMM baseline scorecard",
        "",
        "| Business function | Current average | Target average | Gap |",
        "| --- | ---: | ---: | ---: |",
    ]
    function_rows: dict[str, tuple[float, float]] = {}
    for function in SAMM_FUNCTIONS:
        entries = [
            x for x in samm if x.function == function and x.na_justification is None
        ]
        current = sum(x.current_level for x in entries) / len(entries) if entries else 0
        target = sum(x.target_level for x in entries) / len(entries) if entries else 0
        function_rows[function] = (current, target)
        lines.append(
            f"| {function} | {current:.2f} | {target:.2f} | {target - current:.2f} |"
        )
    current_all = sum(x[0] for x in function_rows.values()) / len(function_rows)
    target_all = sum(x[1] for x in function_rows.values()) / len(function_rows)
    lines.extend(
        [
            "",
            f"Overall average: **{current_all:.2f} / 3.00** (target **{target_all:.2f} / 3.00**).",
            "",
            "Scores exclude entries marked N/A.",
        ]
    )
    samm_md = "\n".join(lines) + "\n"

    grouped: dict[str, Counter[int]] = defaultdict(Counter)
    for activity in dsomm:
        grouped[activity.dimension][activity.level] += 1
    ds_lines = [
        "# DSOMM baseline scorecard",
        "",
        "| Dimension | Level | Implemented | Partial | Planned | N/A |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for dimension in sorted(grouped):
        for level in (1, 2):
            rows = [x for x in dsomm if x.dimension == dimension and x.level == level]
            counts = Counter(x.status for x in rows)
            ds_lines.append(
                f"| {dimension} | {level} | {counts['implemented']} | {counts['partial']} | {counts['planned']} | {counts['na']} |"
            )
    dsomm_md = "\n".join(ds_lines) + "\n"

    gaps: list[tuple[str, str]] = []
    for item in samm:
        if item.na_justification is None and item.current_level < item.target_level:
            gaps.append(
                (
                    "S2",
                    f"- SAMM: **{item.function} / {item.practice} / {item.stream}** — {item.current_level:.1f} vs {item.target_level:.1f}; owner **S2**.",
                )
            )
    for activity in dsomm:
        if activity.status in {"partial", "planned"}:
            gaps.append(
                (
                    activity.planned_in,
                    f"- DSOMM: **{activity.dimension} / {activity.subdimension} / {activity.name}** (L{activity.level}) — {activity.status}; owner **{activity.planned_in}**.",
                )
            )
    gaps.sort(key=lambda pair: (_owner_key(pair[0]), pair[1]))
    gap_md = (
        "# Security gaps\n\nEvidence-backed gaps from the S1 baseline. Planned work is intentionally scored as zero.\n\n"
        + "\n".join(gap for _, gap in gaps)
        + "\n"
    )
    return {
        ROOT / "docs/security/samm/scorecard.md": samm_md,
        ROOT / "docs/security/dsomm/scorecard.md": dsomm_md,
        ROOT / "docs/security/gaps.md": gap_md,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        samm, dsomm = validate()
        for path, content in render(samm, dsomm).items():
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    raise ValueError(f"generated file drift: {path.relative_to(ROOT)}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="
")
    except (OSError, ValueError, TypeError) as error:
        sys.stdout.write(f"security scorecard failed: {error}\n")
        return 1
    sys.stdout.write("security scorecard: OK\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
