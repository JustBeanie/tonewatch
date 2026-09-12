"""Distribution license policy check (S2).

ToneWatch is MIT-licensed. GPL/AGPL libraries linked into the application are not
allowed. GPL/AGPL executables may be bundled as separate programs and invoked as
subprocesses when their notices are included in THIRD_PARTY_NOTICES.md. LGPL is
allowed, but every LGPL package must be named there. Development tools are out of scope.

Inputs are produced by the `just security` recipe:
  --python-requirements  output of `uv export --no-dev --no-emit-project`
  --web-licenses         output of `pnpm --dir web licenses list --prod --json`

This replaces `pip-licenses --fail-on "GPL;AGPL"`, which compares whole license
strings and therefore never matched SPDX names such as `GPL-3.0-or-later`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"

# `\bGPL` cannot match inside "LGPL" (no word boundary between L and G), and the
# "GNU ... General Public License" form excludes "GNU Lesser General Public License".
STRONG_COPYLEFT = re.compile(
    r"\bA?GPL|GNU (?:Affero )?General Public License", re.IGNORECASE
)
LESSER = re.compile(r"\bLGPL|GNU Lesser General Public License", re.IGNORECASE)
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")


@dataclass(frozen=True)
class Package:
    """One dependency and the license text it declares."""

    ecosystem: str
    name: str
    license: str


def classify(license_text: str) -> str:
    """Return ``deny``, ``lgpl`` or ``allow`` for a declared license string.

    SPDX ``OR`` expressions are allowed when any alternative is allowed.
    """
    alternatives = [part.strip(" ()") for part in re.split(r"\s+OR\s+", license_text)]
    verdicts = []
    for alternative in alternatives:
        if STRONG_COPYLEFT.search(alternative):
            verdicts.append("deny")
        elif LESSER.search(alternative):
            verdicts.append("lgpl")
        else:
            verdicts.append("allow")
    for verdict in ("allow", "lgpl"):
        if verdict in verdicts:
            return verdict
    return "deny"


def read_redirected(path: Path) -> str:
    """Read a file produced by shell redirection.

    Windows PowerShell 5.1 `>` writes UTF-16 LE with a BOM; POSIX shells write UTF-8.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def python_packages(requirements: Path) -> list[Package]:
    """Resolve declared licenses for runtime requirements installed in this env."""
    packages = []
    for line in read_redirected(requirements).splitlines():
        match = REQUIREMENT.match(line.strip())
        if match is None:
            continue
        name = match.group(1)
        try:
            meta = metadata.metadata(name)
        except metadata.PackageNotFoundError:
            # Platform-marker dependency not installed on this OS; CI covers Linux.
            continue
        classifiers = [
            c.split("::")[-1].strip()
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        declared = (
            meta.get("License-Expression")
            or meta.get("License")
            or " OR ".join(classifiers)
            or "UNKNOWN"
        )
        packages.append(Package("python", name, declared.strip()))
    return packages


def web_packages(licenses_json: Path) -> list[Package]:
    """Flatten `pnpm licenses list --json` output."""
    data: dict[str, list[dict[str, object]]] = json.loads(
        read_redirected(licenses_json)
    )
    return [
        Package("web", str(entry["name"]), str(entry.get("license") or group))
        for group, entries in data.items()
        for entry in entries
    ]


def check(packages: list[Package], notices_text: str) -> list[str]:
    """Return policy violations (empty when compliant)."""
    problems = []
    for package in packages:
        verdict = classify(package.license)
        if verdict == "deny":
            problems.append(
                f"{package.ecosystem}:{package.name} is strong copyleft ({package.license})"
            )
        elif verdict == "lgpl" and package.name.lower() not in notices_text.lower():
            problems.append(
                f"{package.ecosystem}:{package.name} is LGPL ({package.license}) "
                "but is not named in THIRD_PARTY_NOTICES.md"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the policy check and print a summary."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--python-requirements", type=Path, required=True)
    parser.add_argument("--web-licenses", type=Path, required=True)
    args = parser.parse_args(argv)

    packages = python_packages(args.python_requirements) + web_packages(
        args.web_licenses
    )
    notices = NOTICES.read_text(encoding="utf-8") if NOTICES.exists() else ""
    problems = check(packages, notices)
    for problem in problems:
        sys.stdout.write(f"LICENSE POLICY: {problem}\n")
    sys.stdout.write(
        f"license check: {len(packages)} runtime packages, {len(problems)} violation(s)\n"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
