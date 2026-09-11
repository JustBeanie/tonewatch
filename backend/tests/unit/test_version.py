"""Tests for the bootstrap command-line interface."""

import sys

import pytest

from tonewatch import __version__
from tonewatch.__main__ import main


def test_version_is_defined() -> None:
    """The package exposes a semantic version."""
    assert __version__ == "0.1.0"


def test_version_option(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI prints the package version and exits successfully."""
    monkeypatch.setattr(sys, "argv", ["tonewatch", "--version"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == __version__
