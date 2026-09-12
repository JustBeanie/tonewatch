"""Windows packaging and service seams that remain hermetic on every host."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from tonewatch import service
from tonewatch.settings import Settings

if TYPE_CHECKING:
    import pytest


def test_frozen_data_dir_uses_programdata_only_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.delenv("TONEWATCH_DATA_DIR", raising=False)
    assert Settings().data_dir == tmp_path / "tonewatch"

    configured = tmp_path / "configured"
    monkeypatch.setenv("TONEWATCH_DATA_DIR", str(configured))
    assert Settings().data_dir == configured


def test_unfrozen_data_dir_stays_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("TONEWATCH_DATA_DIR", raising=False)
    assert Settings().data_dir == Path("data")


class FakeServiceManager:
    """Capture service operations without touching the Windows SCM."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path | None, Path | None]] = []

    def install(self, *, executable: Path, data_dir: Path) -> None:
        self.calls.append(("install", executable, data_dir))

    def uninstall(self) -> None:
        self.calls.append(("uninstall", None, None))

    def start(self) -> None:
        self.calls.append(("start", None, None))

    def stop(self) -> None:
        self.calls.append(("stop", None, None))

    def status(self) -> str:
        self.calls.append(("status", None, None))
        return "running"


def test_service_install_passes_frozen_executable_and_data_dir(tmp_path: Path) -> None:
    manager = FakeServiceManager()
    data_dir = tmp_path / "data"
    assert (
        service.run_command(
            "install",
            data_dir=data_dir,
            executable=tmp_path / "tonewatch.exe",
            manager=manager,
            platform_name="win32",
        )
        == 0
    )
    assert manager.calls == [("install", tmp_path / "tonewatch.exe", data_dir)]


def test_service_uninstall_missing_is_clear_and_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    class MissingManager(FakeServiceManager):
        def uninstall(self) -> None:
            raise service.ServiceMissingError("ToneWatch")

    assert service.run_command("uninstall", manager=MissingManager(), platform_name="win32") == 1
    assert "service 'ToneWatch' does not exist" in capsys.readouterr().err


def test_service_subcommand_is_clear_on_non_windows(capsys: pytest.CaptureFixture[str]) -> None:
    assert service.run_command("status", manager=FakeServiceManager(), platform_name="linux") == 2
    assert "only available on Windows" in capsys.readouterr().err


def test_stop_request_reaches_application_shutdown_event() -> None:
    shutdown_event = asyncio.Event()
    stop_requested = Event()

    class FakeServer:
        def __init__(self) -> None:
            self._should_exit = asyncio.Event()

        @property
        def should_exit(self) -> bool:
            return self._should_exit.is_set()

        @should_exit.setter
        def should_exit(self, value: bool) -> None:
            if value:
                self._should_exit.set()

        async def serve(self) -> None:
            await self._should_exit.wait()
            shutdown_event.set()

    async def run() -> None:
        task = asyncio.create_task(
            service.serve_until_stopped(
                Settings(),
                stop_requested,
                server_factory=lambda _config: FakeServer(),
                app_factory=lambda _settings: object(),
            )
        )
        await asyncio.sleep(0)
        stop_requested.set()
        await asyncio.wait_for(task, 1)
        assert shutdown_event.is_set()

    asyncio.run(run())
