"""Check that the uv lockfile's project version matches pyproject.toml."""

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path


def lock_version_matches(project_path: Path, lock_path: Path) -> bool:
    """Return whether the lockfile's ToneWatch version matches the project."""
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    expected = project["project"]["version"]
    matches = [entry for entry in lock["package"] if entry["name"] == "tonewatch"]
    return len(matches) == 1 and matches[0]["version"] == expected


def main(argv: Sequence[str] | None = None) -> int:
    """Return zero when the lockfile contains the current project version."""
    root = Path(__file__).parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path", nargs="?", type=Path)
    parser.add_argument("lock_path", nargs="?", type=Path)
    args = parser.parse_args(argv)
    project_path = args.project_path or root / "backend" / "pyproject.toml"
    lock_path = args.lock_path or root / "backend" / "uv.lock"
    if not lock_version_matches(project_path, lock_path):
        sys.stderr.write("backend/uv.lock tonewatch version does not match pyproject.toml\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
