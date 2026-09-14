"""Windows service integration and the testable service-manager seam."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from tonewatch.logging import configure_logging
from tonewatch.settings import Settings

SERVICE_NAME = "ToneWatch"
SERVICE_DISPLAY_NAME = "ToneWatch"
SERVICE_DESCRIPTION = "ToneWatch radio notification service"
ERROR_SERVICE_DOES_NOT_EXIST = 1060
SERVICE_STATE_TIMEOUT_S = 30.0
SERVICE_STATE_POLL_S = 0.1

if TYPE_CHECKING:
    from collections.abc import Callable

    class _ServiceFramework:
        """Type-only subset of the pywin32 service base class."""

        def __init__(self, args: list[str]) -> None: ...

        def ReportServiceStatus(self, state: int) -> None:  # noqa: N802 -- pywin32 API name.
            ...

else:

    class _ServiceFramework:
        """Import-time stand-in so service tests run on Linux."""

        def __init__(self, _args: list[str]) -> None:
            pass


win32service: Any = None
win32con: Any = None
if sys.platform == "win32":
    win32service = importlib.import_module("win32service")
    win32con = importlib.import_module("win32con")
    globals()["_ServiceFramework"] = importlib.import_module("win32serviceutil").ServiceFramework


class ServiceMissingError(RuntimeError):
    """Raised when an SCM operation targets a service that is not installed."""


class ServiceUnavailableError(RuntimeError):
    """Raised when a Windows-only service operation is requested elsewhere."""


class ServiceStateTimeoutError(RuntimeError):
    """Raised when the SCM does not reach a requested state in time."""

    def __init__(self, expected_name: str, last_state: str) -> None:
        """Build a clear bounded-wait failure message."""
        super().__init__(
            f"service {SERVICE_NAME} did not reach {expected_name} within "
            f"{SERVICE_STATE_TIMEOUT_S:g}s (last state: {last_state})"
        )


class ServiceManager(Protocol):
    """Operations needed by the CLI, injectable for hermetic unit tests."""

    def install(self, *, executable: Path, data_dir: Path) -> None:
        """Install the service."""

    def uninstall(self) -> None:
        """Remove the service."""

    def start(self) -> None:
        """Start the service."""

    def stop(self) -> None:
        """Stop the service gracefully."""

    def status(self) -> str:
        """Return a human-readable service state."""


def _service_command(executable: Path, data_dir: Path) -> str:
    """Build the SCM command line, preserving the frozen data directory."""
    quoted_executable = f'"{executable}"'
    quoted_data_dir = f'"{data_dir}"'
    if getattr(sys, "frozen", False):
        return f"{quoted_executable} service-run --data-dir {quoted_data_dir}"
    return f"{quoted_executable} -m tonewatch service-run --data-dir {quoted_data_dir}"


def _is_missing_error(error: Exception) -> bool:
    """Recognize the Windows SCM's service-not-found error without importing it on Linux."""
    return getattr(error, "winerror", None) == ERROR_SERVICE_DOES_NOT_EXIST or error.args[:1] == (
        ERROR_SERVICE_DOES_NOT_EXIST,
    )


def _win32_manager() -> ServiceManager:
    """Create the real pywin32 SCM adapter."""
    if sys.platform != "win32":
        raise ServiceUnavailableError
    return _WindowsServiceManager()


class ToneWatchService(_ServiceFramework):
    """pywin32 service wrapper that lets uvicorn execute its normal lifespan shutdown."""

    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args: list[str]) -> None:
        """Initialize the SCM wrapper and its cooperative stop event."""
        super().__init__(args)
        self._stop_requested = threading.Event()

    def SvcStop(self) -> None:  # noqa: N802 -- pywin32 requires this callback name.
        """Ask uvicorn to exit so FastAPI lifespan finalization flushes recordings."""
        if sys.platform == "win32":
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_requested.set()

    def SvcDoRun(self) -> None:  # noqa: N802 -- pywin32 requires this callback name.
        """Run the application until the SCM sends a stop control."""
        settings = Settings.load()
        configure_logging(settings.log_level, json=True, data_dir=settings.data_dir)
        logger = structlog.get_logger("tonewatch.service")
        logger.info("service starting", data_dir=str(settings.data_dir))
        try:
            asyncio.run(serve_until_stopped(settings, self._stop_requested))
        finally:
            logger.info("service stopped")


class _WindowsServiceManager:
    """Small pywin32 adapter for the Windows Service Control Manager."""

    def install(self, *, executable: Path, data_dir: Path) -> None:
        """Install delayed automatic startup with restart-on-failure recovery."""
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CREATE_SERVICE)
        handle: Any = None
        try:
            handle = win32service.CreateService(
                manager,
                SERVICE_NAME,
                SERVICE_DISPLAY_NAME,
                win32service.SERVICE_ALL_ACCESS,
                win32service.SERVICE_WIN32_OWN_PROCESS,
                win32service.SERVICE_AUTO_START,
                win32service.SERVICE_ERROR_NORMAL,
                _service_command(executable, data_dir),
                None,
                0,
                None,
                None,
                None,
            )
            win32service.ChangeServiceConfig2(
                handle,
                win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
                True,
            )
            win32service.ChangeServiceConfig2(
                handle,
                win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                {
                    "ResetPeriod": 86400,
                    "RebootMsg": "",
                    "Command": "",
                    "Actions": [(win32service.SC_ACTION_RESTART, 60000)],
                },
            )
        except Exception as error:
            if _is_missing_error(error):
                raise ServiceMissingError(SERVICE_NAME) from error
            raise
        finally:
            if handle is not None:
                win32service.CloseServiceHandle(handle)
            win32service.CloseServiceHandle(manager)

    def uninstall(self) -> None:
        """Delete the service registration."""
        handle = self._open(win32con.DELETE)
        try:
            win32service.DeleteService(handle)
        except Exception as error:
            if _is_missing_error(error):
                raise ServiceMissingError(SERVICE_NAME) from error
            raise
        finally:
            win32service.CloseServiceHandle(handle)

    def start(self) -> None:
        """Start the registered service."""
        handle = self._open(win32service.SERVICE_START | win32service.SERVICE_QUERY_STATUS)
        try:
            win32service.StartService(handle, None)
            self._wait_for_state(handle, win32service.SERVICE_RUNNING, "running")
        finally:
            win32service.CloseServiceHandle(handle)

    def stop(self) -> None:
        """Send a cooperative stop control to the service process."""
        handle = self._open(win32service.SERVICE_STOP | win32service.SERVICE_QUERY_STATUS)
        try:
            state = win32service.QueryServiceStatus(handle)[1]
            if state != win32service.SERVICE_STOPPED:
                if state != win32service.SERVICE_STOP_PENDING:
                    win32service.ControlService(handle, win32service.SERVICE_CONTROL_STOP)
                self._wait_for_state(handle, win32service.SERVICE_STOPPED, "stopped")
        finally:
            win32service.CloseServiceHandle(handle)

    def status(self) -> str:
        """Return the SCM state."""
        handle = self._open(win32service.SERVICE_QUERY_STATUS)
        try:
            state = win32service.QueryServiceStatus(handle)[1]
        finally:
            win32service.CloseServiceHandle(handle)
        return self._state_name(state)

    @classmethod
    def _state_name(cls, state: int) -> str:
        names = (
            ("SERVICE_STOPPED", "stopped"),
            ("SERVICE_START_PENDING", "start_pending"),
            ("SERVICE_STOP_PENDING", "stop_pending"),
            ("SERVICE_RUNNING", "running"),
            ("SERVICE_CONTINUE_PENDING", "continue_pending"),
            ("SERVICE_PAUSE_PENDING", "pause_pending"),
            ("SERVICE_PAUSED", "paused"),
        )
        for constant, name in names:
            if getattr(win32service, constant, None) == state:
                return name
        return f"state-{state}"

    @classmethod
    def _wait_for_state(cls, handle: Any, expected: int, expected_name: str) -> None:
        deadline = time.monotonic() + SERVICE_STATE_TIMEOUT_S
        while True:
            state = win32service.QueryServiceStatus(handle)[1]
            if state == expected:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServiceStateTimeoutError(expected_name, cls._state_name(state))
            time.sleep(min(SERVICE_STATE_POLL_S, remaining))

    @staticmethod
    def _open(access: int) -> Any:
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            return win32service.OpenService(manager, SERVICE_NAME, access)
        except Exception as error:
            win32service.CloseServiceHandle(manager)
            if _is_missing_error(error):
                raise ServiceMissingError(SERVICE_NAME) from error
            raise


async def serve_until_stopped(
    settings: Any,
    stop_requested: threading.Event,
    *,
    server_factory: Callable[[Any], Any] | None = None,
    app_factory: Callable[[Any], Any] | None = None,
) -> None:
    """Run uvicorn until the SCM stop event asks it to execute lifespan shutdown."""
    import uvicorn  # noqa: PLC0415 -- lazy import keeps the service seam importable in tests.

    from tonewatch.api.app import create_app  # noqa: PLC0415 -- see the uvicorn import above.

    application = (app_factory or create_app)(settings)
    config = uvicorn.Config(
        application,
        host=settings.bind_host,
        port=settings.bind_port,
        timeout_keep_alive=5,
        h11_max_incomplete_event_size=64 * 1024,
        limit_concurrency=100,
        # Uvicorn access logging remains enabled by its default.
        log_config=None,
    )
    server = (server_factory or uvicorn.Server)(config)

    async def wait_for_stop() -> None:
        while not await asyncio.to_thread(stop_requested.wait, 0.05):
            pass

    server_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(wait_for_stop())
    done, _ = await asyncio.wait((server_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
    if stop_task in done and not server_task.done():
        server.should_exit = True
    if not server_task.done():
        await server_task
    if stop_task not in done:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


def run_command(
    action: str,
    *,
    data_dir: Path | None = None,
    executable: Path | None = None,
    manager: ServiceManager | None = None,
    platform_name: str | None = None,
) -> int:
    """Run one service command and return its process exit code."""
    if (platform_name or sys.platform) != "win32":
        sys.stderr.write("the service subcommand is only available on Windows\n")
        return 2
    selected = manager or _win32_manager()
    try:
        if action == "install":
            selected.install(
                executable=executable or Path(sys.executable),
                data_dir=data_dir or Path(os.environ.get("TONEWATCH_DATA_DIR", "data")),
            )
        elif action == "uninstall":
            selected.uninstall()
        elif action == "start":
            selected.start()
        elif action == "stop":
            selected.stop()
        elif action == "status":
            sys.stdout.write(f"{selected.status()}\n")
        else:
            sys.stderr.write(f"unknown service action: {action}\n")
            return 2
    except ServiceMissingError:
        sys.stderr.write(f"service '{SERVICE_NAME}' does not exist\n")
        return 1
    except Exception as error:
        sys.stderr.write(f"service {action} failed: {error}\n")
        return 1
    if action != "status":
        sys.stdout.write(f"service {SERVICE_NAME}: {action} succeeded\n")
    return 0


def run_service_process(data_dir: Path) -> None:
    """Enter the pywin32 dispatcher from the frozen service executable."""
    if sys.platform != "win32":
        raise ServiceUnavailableError
    servicemanager = importlib.import_module("servicemanager")

    os.environ["TONEWATCH_DATA_DIR"] = str(data_dir)
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(ToneWatchService)
    servicemanager.StartServiceCtrlDispatcher()
