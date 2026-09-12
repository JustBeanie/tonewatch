"""Tests for the bootstrap command-line interface."""

import sys
from importlib import metadata

import pytest

from tonewatch import __version__
from tonewatch.__main__ import main


def test_version_is_defined() -> None:
    """The package version is X.Y.Z and matches its installed metadata.

    release-please bumps the version, so the test must not hardcode one.
    """
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
    assert __version__ == metadata.version("tonewatch")


def test_version_option(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI prints the package version and exits successfully."""
    monkeypatch.setattr(sys, "argv", ["tonewatch", "--version"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == __version__
