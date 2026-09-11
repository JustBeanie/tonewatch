"""Tests for the distribution license policy check."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts/license_check.py"
SPEC = importlib.util.spec_from_file_location("license_check", SCRIPT)
assert SPEC and SPEC.loader
license_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = license_check
SPEC.loader.exec_module(license_check)


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("MIT", "allow"),
        ("BSD-3-Clause", "allow"),
        ("Apache-2.0", "allow"),
        # The regression: pip-licenses --fail-on "GPL" never matched these.
        ("GPL-3.0-or-later", "deny"),
        ("GPL-2.0-only", "deny"),
        ("AGPL-3.0", "deny"),
        ("GNU General Public License v3 (GPLv3)", "deny"),
        ("GNU Affero General Public License v3", "deny"),
        ("LGPL-2.1-or-later", "lgpl"),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", "lgpl"),
        ("MIT OR GPL-2.0", "allow"),
        ("(LGPL-3.0 OR GPL-3.0)", "lgpl"),
    ],
)
def test_classify(text: str, verdict: str) -> None:
    assert license_check.classify(text) == verdict


def test_check_flags_copyleft_and_unlisted_lgpl() -> None:
    packages = [
        license_check.Package("python", "yamllint", "GPL-3.0-or-later"),
        license_check.Package("python", "av", "BSD-3-Clause"),
        license_check.Package("web", "somelib", "LGPL-2.1"),
        license_check.Package("web", "listed", "LGPL-3.0"),
    ]
    problems = license_check.check(packages, "listed is bundled under LGPL")
    assert len(problems) == 2
    assert "yamllint" in problems[0]
    assert "somelib" in problems[1]


def test_main_reads_uv_export_and_pnpm_json(tmp_path: Path) -> None:
    requirements = tmp_path / "req.txt"
    requirements.write_text(
        "pydantic==2.13.5 \\\n    --hash=sha256:abc\nnot-installed-anywhere==1.0\n",
        encoding="utf-8",
    )
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"MIT": [{"name": "react", "license": "MIT"}]}), encoding="utf-8")
    assert (
        license_check.main(["--python-requirements", str(requirements), "--web-licenses", str(web)])
        == 0
    )

    web.write_text(
        json.dumps({"GPL-3.0": [{"name": "bad", "license": "GPL-3.0"}]}), encoding="utf-8"
    )
    assert (
        license_check.main(["--python-requirements", str(requirements), "--web-licenses", str(web)])
        == 1
    )


def test_reads_powershell_utf16_redirect(tmp_path: Path) -> None:
    # Windows PowerShell 5.1 `>` writes UTF-16 LE with a BOM.
    path = tmp_path / "web.json"
    path.write_text(json.dumps({"MIT": [{"name": "react"}]}), encoding="utf-16")
    assert license_check.web_packages(path) == [license_check.Package("web", "react", "MIT")]
