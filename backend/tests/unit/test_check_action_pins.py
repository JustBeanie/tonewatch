"""Unit tests for scripts/check_action_pins.py with a fake git ls-remote."""

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "check_action_pins.py"
_spec = importlib.util.spec_from_file_location("check_action_pins", SCRIPT)
assert _spec is not None and _spec.loader is not None
pins: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins)

COMMIT = "a" * 40
TAG_OBJECT = "b" * 40
OTHER = "c" * 40

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _runner(stdout: str, returncode: int = 0) -> Runner:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run


def _workflow(tmp_path: Path, sha: str, tag: str = "v1.2.3") -> str:
    path = tmp_path / "wf.yml"
    path.write_text(
        f"jobs:\n  a:\n    steps:\n      - uses: owner/repo@{sha} # {tag}\n", encoding="utf-8"
    )
    return str(path)


def test_lightweight_tag_matching_commit_passes(tmp_path: Path) -> None:
    runner = _runner(f"{COMMIT}\trefs/tags/v1.2.3\n")
    assert pins.main([_workflow(tmp_path, COMMIT)], runner) == 0


def test_annotated_tag_requires_the_peeled_commit(tmp_path: Path) -> None:
    runner = _runner(f"{TAG_OBJECT}\trefs/tags/v1.2.3\n{COMMIT}\trefs/tags/v1.2.3^{{}}\n")
    assert pins.main([_workflow(tmp_path, COMMIT)], runner) == 0
    assert pins.main([_workflow(tmp_path, TAG_OBJECT)], runner) == 1


def test_wrong_label_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _runner(f"{OTHER}\trefs/tags/v1.2.3\n")
    assert pins.main([_workflow(tmp_path, COMMIT)], runner) == 1
    assert "is not v1.2.3" in capsys.readouterr().err


def test_missing_tag_fails_instead_of_skipping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner("")
    assert pins.main([_workflow(tmp_path, COMMIT)], runner) == 1
    assert "does not exist" in capsys.readouterr().err


def test_offline_skips_with_notice(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _runner("", returncode=128)
    assert pins.main([_workflow(tmp_path, COMMIT)], runner) == 0
    assert "skipped" in capsys.readouterr().out


def test_major_only_label_is_rejected(tmp_path: Path) -> None:
    assert pins.main([_workflow(tmp_path, COMMIT, tag="v5")], _runner("")) == 1
