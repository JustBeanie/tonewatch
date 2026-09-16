"""Tests for the Linux runtime dependency export gate."""

from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path
from runpy import run_path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "check_runtime_export.py"
validate_runtime_export = cast(
    "Callable[[str], None]", run_path(str(_CHECKER))["validate_runtime_export"]
)


def test_runtime_export_accepts_win32_marker_only_packages() -> None:
    validate_runtime_export(
        """
        fastapi==0.1
        tzdata==2026.1
        pywin32==312 ; sys_platform == 'win32'
        pywin32-ctypes==0.2.3 ; sys_platform == "win32"
        """
    )


@pytest.mark.parametrize(
    "requirement",
    [
        "pyinstaller==6.22.2",
        "altgraph==0.17.5",
        "pefile==2024.8.26",
        "pywin32==312",
        "pywin32-ctypes==0.2.3 ; sys_platform != 'linux'",
        "pywin32-extra==1.0 ; sys_platform == 'win32'",
    ],
)
def test_runtime_export_rejects_packaging_or_broad_windows_dependencies(
    requirement: str,
) -> None:
    with pytest.raises(ValueError, match="invalid Linux runtime export"):
        validate_runtime_export(requirement)


def test_runtime_export_includes_tzdata() -> None:
    assert distribution("tzdata").metadata["Name"] == "tzdata"
    validate_runtime_export("tzdata==2026.1\n")
