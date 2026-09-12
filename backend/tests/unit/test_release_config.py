"""Regression tests for the release-please manifest configuration."""

import json
import re
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).parents[3]
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return cast("dict[str, object]", data)


def test_release_please_manifest_and_lockfile_updater() -> None:
    config = _load_json(ROOT / "release-please-config.json")
    manifest = _load_json(ROOT / ".release-please-manifest.json")
    packages = cast("dict[str, object]", config["packages"])
    backend = cast("dict[str, object]", packages["backend"])

    assert config["separate-pull-requests"] is True
    assert config["include-component-in-tag"] is False
    assert backend["component"] == "backend"
    manifest_version = manifest["backend"]
    assert isinstance(manifest_version, str)
    assert SEMVER.fullmatch(manifest_version)

    assert backend["extra-files"] == [
        {
            "type": "toml",
            "path": "backend/uv.lock",
            "jsonpath": '$.package[?(@.name == "tonewatch")].version',
        }
    ]

    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    package_entries = [entry for entry in lock["package"] if entry["name"] == "tonewatch"]
    assert len(package_entries) == 1
