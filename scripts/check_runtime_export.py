"""Validate that a Linux runtime export excludes packaging-only dependencies."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

_FORBIDDEN = frozenset({"pyinstaller", "altgraph", "pefile"})
_WINDOWS_MARKER_ONLY = frozenset({"pywin32", "pywin32-ctypes"})
_WIN32_MARKER = re.compile(r"^sys_platform\s*==\s*['\"]win32['\"]$")


def _requirements(export: str) -> list[tuple[Requirement, str]]:
    """Parse requirement lines and retain each original line for marker validation."""
    parsed: list[tuple[Requirement, str]] = []
    for line_number, raw_line in enumerate(export.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement_line = line.split(" #", 1)[0].strip().removesuffix("\\").strip()
        try:
            parsed.append((Requirement(requirement_line), requirement_line))
        except InvalidRequirement as error:
            raise ValueError(
                f"invalid requirement on line {line_number}: {raw_line}"
            ) from error
    return parsed


def validate_runtime_export(export: str) -> None:
    """Raise when the export contains packaging-only or incorrectly marked Windows packages."""
    violations: list[str] = []
    names: set[str] = set()
    for requirement, original in _requirements(export):
        name = requirement.name.casefold().replace("_", "-")
        names.add(name)
        if name in _FORBIDDEN:
            violations.append(f"{name} must be absent: {original}")
            continue
        if name in _WINDOWS_MARKER_ONLY:
            marker = original.split(";", 1)[1].strip() if ";" in original else ""
            if _WIN32_MARKER.fullmatch(marker) is None:
                violations.append(
                    f"{name} must use only sys_platform == 'win32': {original}"
                )
        elif name.startswith("pywin32"):
            violations.append(f"unexpected Windows-only package: {original}")
    if "tzdata" not in names:
        violations.append("missing required runtime dependency: tzdata")
    if violations:
        raise ValueError("invalid Linux runtime export:\n" + "\n".join(violations))


def main() -> int:
    """Validate the requirements file named on the command line."""
    if len(sys.argv) != 2:
        sys.stderr.write("usage: check_runtime_export.py REQUIREMENTS.txt\n")
        return 2
    try:
        raw = Path(sys.argv[1]).read_bytes()
        encoding = (
            "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
        validate_runtime_export(raw.decode(encoding))
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
