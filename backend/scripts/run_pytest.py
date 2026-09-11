"""Run pytest with a fresh per-run temp root inside the repo.

The Codex sandbox runs as a different Windows account that reports the same
user name, so pytest's default ``%TEMP%/pytest-of-<user>`` and any fixed
``--basetemp`` end up owned by whichever account ran first and are unusable
(pytest must delete them) for the other. A unique directory per run avoids
sharing entirely; stale ones are removed best-effort.
"""

import shutil
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
TMP_ROOT = BACKEND / ".pytest-tmp"


def main() -> int:
    """Run pytest with a unique basetemp and return its exit code."""
    TMP_ROOT.mkdir(exist_ok=True)
    for stale in TMP_ROOT.iterdir():
        shutil.rmtree(stale, ignore_errors=True)
    basetemp = TMP_ROOT / uuid.uuid4().hex
    args = ["-c", str(BACKEND / "pyproject.toml"), f"--basetemp={basetemp}", *sys.argv[1:]]
    return int(pytest.main(args))


if __name__ == "__main__":
    sys.exit(main())
