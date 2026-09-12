"""Windows packaging and service seams that remain hermetic on every host."""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from tonewatch import service
from tonewatch.logging import configure_logging
from tonewatch.settings import Settings


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


class FakeScm:
    """Minimal SCM API that exposes a scripted sequence of service states."""

    SC_MANAGER_CREATE_SERVICE = 2
    SC_MANAGER_CONNECT = 8
    SERVICE_ALL_ACCESS = 983551
    SERVICE_WIN32_OWN_PROCESS = 16
    SERVICE_AUTO_START = 2
    SERVICE_ERROR_NORMAL = 1
    SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3
    SERVICE_CONFIG_FAILURE_ACTIONS = 2
    SC_ACTION_RESTART = 1
    SERVICE_START = 16
    SERVICE_STOP = 2
    SERVICE_QUERY_STATUS = 4
    SERVICE_RUNNING = 4
    SERVICE_STOPPED = 1
    SERVICE_START_PENDING = 2
    SERVICE_STOP_PENDING = 3
    SERVICE_CONTINUE_PENDING = 5
    SERVICE_PAUSE_PENDING = 6
    SERVICE_PAUSED = 7
    SERVICE_CONTROL_STOP = 1

    def __init__(self, states: list[int], *, missing_on_open: bool = False) -> None:
        self.states = states
        self.missing_on_open = missing_on_open
        self.opened_access: list[int] = []
        self.created: tuple[object, ...] | None = None
        self.config_changes: list[tuple[object, ...]] = []
        self.start_called = False
        self.stop_called = False
        self.delete_called = False

    def OpenSCManager(self, *_args: object) -> object:  # noqa: N802 -- fake pywin32 API.
        return SimpleNamespace(kind="manager")

    def OpenService(self, _manager: object, _name: str, access: int) -> object:  # noqa: N802 -- fake pywin32 API.
        self.opened_access.append(access)
        if self.missing_on_open:
            raise OSError(1060)
        return SimpleNamespace(kind="service")

    def CreateService(self, *args: object) -> object:  # noqa: N802 -- fake pywin32 API.
        self.created = args
        return SimpleNamespace(kind="service")

    def ChangeServiceConfig2(self, *args: object) -> None:  # noqa: N802 -- fake pywin32 API.
        self.config_changes.append(args)

    def DeleteService(self, _handle: object) -> None:  # noqa: N802 -- fake pywin32 API.
        self.delete_called = True

    def CloseServiceHandle(self, _handle: object) -> None:  # noqa: N802 -- fake pywin32 API.
        return None

    def StartService(self, *_args: object) -> None:  # noqa: N802 -- fake pywin32 API.
        self.start_called = True

    def ControlService(self, *_args: object) -> None:  # noqa: N802 -- fake pywin32 API.
        self.stop_called = True

    def QueryServiceStatus(self, _handle: object) -> tuple[int, int, int, int, int, int, int]:  # noqa: N802 -- fake pywin32 API.
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return (0, state, 0, 0, 0, 0, 0)


class FakeWin32Con:
    """Minimal win32con namespace used by the real service manager tests."""

    DELETE = 0x00010000


SERVICE_CONSTANTS = (
    "SC_MANAGER_CREATE_SERVICE",
    "SC_MANAGER_CONNECT",
    "SERVICE_ALL_ACCESS",
    "SERVICE_WIN32_OWN_PROCESS",
    "SERVICE_AUTO_START",
    "SERVICE_ERROR_NORMAL",
    "SERVICE_CONFIG_DELAYED_AUTO_START_INFO",
    "SERVICE_CONFIG_FAILURE_ACTIONS",
    "SC_ACTION_RESTART",
    "SERVICE_START",
    "SERVICE_QUERY_STATUS",
    "SERVICE_RUNNING",
    "SERVICE_STOP",
    "SERVICE_STOPPED",
    "SERVICE_STOP_PENDING",
    "SERVICE_CONTROL_STOP",
    "SERVICE_START_PENDING",
    "SERVICE_CONTINUE_PENDING",
    "SERVICE_PAUSE_PENDING",
    "SERVICE_PAUSED",
)


def test_windows_service_stop_waits_for_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    scm = FakeScm([FakeScm.SERVICE_RUNNING, FakeScm.SERVICE_STOP_PENDING, FakeScm.SERVICE_STOPPED])
    monkeypatch.setattr(service, "win32service", scm)
    manager = service._WindowsServiceManager()

    manager.stop()

    assert scm.stop_called


def test_windows_service_uninstall_uses_delete_access_and_deletes_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scm = FakeScm([])
    monkeypatch.setattr(service, "win32service", scm)
    monkeypatch.setattr(service, "win32con", FakeWin32Con)

    service._WindowsServiceManager().uninstall()

    assert scm.opened_access == [FakeWin32Con.DELETE]
    assert scm.delete_called


def test_windows_service_uninstall_missing_is_clear_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scm = FakeScm([], missing_on_open=True)
    monkeypatch.setattr(service, "win32service", scm)
    monkeypatch.setattr(service, "win32con", FakeWin32Con)

    assert service.run_command("uninstall", platform_name="win32") == 1
    assert "service 'ToneWatch' does not exist" in capsys.readouterr().err


def test_windows_service_install_uses_real_manager(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scm = FakeScm([])
    monkeypatch.setattr(service, "win32service", scm)
    executable = tmp_path / "tonewatch.exe"
    data_dir = tmp_path / "data"

    service._WindowsServiceManager().install(executable=executable, data_dir=data_dir)

    assert scm.created is not None
    assert scm.created[1:3] == (service.SERVICE_NAME, service.SERVICE_DISPLAY_NAME)
    assert scm.created[7] == service._service_command(executable, data_dir)
    assert len(scm.config_changes) == 2


def test_pywin32_exports_service_constants_on_windows() -> None:
    """The constants used by the service adapter must be exported by pywin32."""
    if sys.platform != "win32":
        pytest.skip("pywin32 exports are available only on Windows")

    win32con = importlib.import_module("win32con")
    win32service = importlib.import_module("win32service")
    win32serviceutil = importlib.import_module("win32serviceutil")

    assert hasattr(win32con, "DELETE")
    for name in SERVICE_CONSTANTS:
        assert hasattr(win32service, name), name
    assert hasattr(win32serviceutil, "ServiceFramework")


def test_windows_service_stop_timeout_is_clear_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    scm = FakeScm([FakeScm.SERVICE_STOP_PENDING])
    monkeypatch.setattr(service, "win32service", scm)
    monkeypatch.setattr(service, "SERVICE_STATE_TIMEOUT_S", 0.01)
    manager = service._WindowsServiceManager()

    with pytest.raises(service.ServiceStateTimeoutError, match="did not reach stopped"):
        manager.stop()


def test_windows_service_start_waits_for_running(monkeypatch: pytest.MonkeyPatch) -> None:
    scm = FakeScm([FakeScm.SERVICE_START_PENDING, FakeScm.SERVICE_RUNNING])
    monkeypatch.setattr(service, "win32service", scm)
    manager = service._WindowsServiceManager()

    manager.start()

    assert scm.start_called


def test_windows_service_status_uses_exact_state_names(monkeypatch: pytest.MonkeyPatch) -> None:
    states = {
        FakeScm.SERVICE_RUNNING: "running",
        FakeScm.SERVICE_STOPPED: "stopped",
        FakeScm.SERVICE_START_PENDING: "start_pending",
        FakeScm.SERVICE_STOP_PENDING: "stop_pending",
        FakeScm.SERVICE_CONTINUE_PENDING: "continue_pending",
        FakeScm.SERVICE_PAUSE_PENDING: "pause_pending",
        FakeScm.SERVICE_PAUSED: "paused",
    }
    for state, expected in states.items():
        scm = FakeScm([state])
        monkeypatch.setattr(service, "win32service", scm)
        assert service._WindowsServiceManager().status() == expected


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


def test_service_server_does_not_configure_missing_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service host with detached stdio must still construct its uvicorn server."""
    stop_requested = Event()

    class FakeServer:
        def __init__(self) -> None:
            self._stopped = asyncio.Event()

        @property
        def should_exit(self) -> bool:
            return self._stopped.is_set()

        @should_exit.setter
        def should_exit(self, value: bool) -> None:
            if value:
                self._stopped.set()

        async def serve(self) -> None:
            await self._stopped.wait()

    async def run() -> None:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
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

    asyncio.run(run())


def test_service_logging_routes_detached_stdio_to_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Service logging must not retain a handler whose stream is None."""
    previous_handlers = logging.getLogger().handlers[:]
    try:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        configure_logging("INFO", data_dir=tmp_path)
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.FileHandler)
        assert (tmp_path / "tonewatch.log").is_file()
    finally:
        for handler in logging.getLogger().handlers:
            handler.close()
        logging.getLogger().handlers[:] = previous_handlers


def test_windows_service_logs_start_and_shutdown_when_stdio_is_detached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The SCM host records lifecycle lines even when Windows detaches stdio."""
    previous_handlers = logging.getLogger().handlers[:]
    try:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        monkeypatch.setattr(service.Settings, "load", lambda: Settings(data_dir=tmp_path))

        def fake_run(coro: Any) -> None:
            coro.close()

        monkeypatch.setattr(service.asyncio, "run", fake_run)
        instance = object.__new__(service.ToneWatchService)
        instance._stop_requested = Event()
        instance.SvcDoRun()

        log = (tmp_path / "tonewatch.log").read_text(encoding="utf-8")
        assert "service starting" in log
        assert "service stopped" in log
    finally:
        for handler in logging.getLogger().handlers:
            handler.close()
        logging.getLogger().handlers[:] = previous_handlers
