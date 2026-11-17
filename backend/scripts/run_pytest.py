"""Run pytest with a fresh per-run temp root inside the repo.

The Codex sandbox runs as a different Windows account that reports the same
user name, so pytest's default ``%TEMP%/pytest-of-<user>`` and any fixed
``--basetemp`` end up owned by whichever account ran first and are unusable
(pytest must delete them) for the other. Each invocation owns its temporary
directory so it can run alongside a benchmark or another test suite.
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

BACKEND = Path(__file__).resolve().parent.parent
TMP_ROOT = BACKEND / ".pytest-tmp"


def main() -> int:
    """Run pytest with a unique basetemp and return its exit code."""
    TMP_ROOT.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=TMP_ROOT, ignore_cleanup_errors=True) as run_dir:
        basetemp = Path(run_dir) / "pytest"
        args = ["-c", str(BACKEND / "pyproject.toml"), f"--basetemp={basetemp}", *sys.argv[1:]]
        return int(pytest.main(args))


if __name__ == "__main__":
    sys.exit(main())
