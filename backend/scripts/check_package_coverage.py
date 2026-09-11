"""Enforce the stricter coverage gate for DSP and pipeline packages."""

import json
import sys
from pathlib import Path
from typing import Any

REPORT = Path("coverage.json")
SOURCE_ROOT = Path("backend/src/tonewatch")
PACKAGES = ("dsp", "pipeline", "sources")
MINIMUMS = {"dsp": 95.0, "pipeline": 95.0, "sources": 90.0}


def package_coverage(report: dict[str, Any], package: str) -> float:
    """Return line coverage for one package from a coverage.py JSON report."""
    package_root = (SOURCE_ROOT / package).as_posix()
    covered = 0
    statements = 0
    for filename, details in report["files"].items():
        normalized = Path(filename).as_posix()
        if normalized.startswith(package_root + "/"):
            summary = details["summary"]
            covered += summary["covered_lines"]
            statements += summary["num_statements"]
    return 100.0 if statements == 0 else covered * 100.0 / statements


def main() -> int:
    """Check existing strict-gated packages and skip future packages not yet scaffolded."""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    failures: list[str] = []
    for package in PACKAGES:
        if not (SOURCE_ROOT / package).is_dir():
            continue
        percentage = package_coverage(report, package)
        minimum = MINIMUMS[package]
        if percentage < minimum:
            failures.append(f"{package}: {percentage:.2f}% < {minimum:.2f}%")
    if failures:
        for failure in failures:
            sys.stdout.write(f"{failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
