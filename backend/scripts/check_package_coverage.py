"""Enforce the stricter coverage gate for DSP and pipeline packages."""

import json
import sys
from pathlib import Path
from typing import Any

REPORT = Path("coverage.json")
SOURCE_ROOT = Path("backend/src/tonewatch")
PACKAGES = ("dsp", "pipeline", "sources", "recording")
MINIMUMS = {"dsp": 95.0, "pipeline": 95.0, "sources": 90.0, "recording": 90.0}
MODULE_GATES = {
    "api": (SOURCE_ROOT / "api").rglob("*.py"),
    "integrations": (SOURCE_ROOT / "integrations").rglob("*.py"),
}


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


def module_coverage(report: dict[str, Any], filename: Path) -> float:
    """Return line coverage for one API module."""
    target = filename.as_posix()
    for report_name, details in report["files"].items():
        if Path(report_name).as_posix() == target:
            summary = details["summary"]
            statements = summary["num_statements"]
            return 100.0 if statements == 0 else summary["covered_lines"] * 100.0 / statements
    return 100.0


def main() -> int:
    """Check existing strict-gated packages and skip future packages not yet scaffolded."""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    failures: list[str] = []
    for package in PACKAGES:
        if not (SOURCE_ROOT / package).is_dir():
            continue
        percentage = package_coverage(report, package)
        minimum = MINIMUMS[package]
        sys.stdout.write(f"{package}: {percentage:.2f}% (minimum {minimum:.2f}%)\n")
        if percentage < minimum:
            failures.append(f"{package}: {percentage:.2f}% < {minimum:.2f}%")
    for modules in MODULE_GATES.values():
        minimum = 90.0
        for module in modules:
            percentage = module_coverage(report, module)
            sys.stdout.write(
                f"{module.relative_to(SOURCE_ROOT.parent)}: {percentage:.2f}% (minimum 90.00%)\n"
            )
            if percentage < minimum:
                failures.append(
                    f"{module.relative_to(SOURCE_ROOT.parent)}: {percentage:.2f}% < 90.00%"
                )
    if failures:
        for failure in failures:
            sys.stdout.write(f"{failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
