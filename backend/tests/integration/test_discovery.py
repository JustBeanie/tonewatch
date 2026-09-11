"""M5.5 and M5.6 discovery/generation contract tests."""

import runpy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, cast

import pytest

from tonewatch.integrations import supervisor as supervisor_module
from tonewatch.integrations import zeroconf as zeroconf_module


class FakeZeroconf:
    instances: ClassVar[list["FakeZeroconf"]] = []

    def __init__(self) -> None:
        self.registered: list[Any] = []
        self.unregistered: list[Any] = []
        self.closed = False
        self.instances.append(self)

    async def async_register_service(self, info) -> None:
        self.registered.append(info)

    async def async_unregister_service(self, info) -> None:
        self.unregistered.append(info)

    async def async_close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_zeroconf_registers_txt_without_token_and_unregisters(monkeypatch) -> None:
    monkeypatch.setattr(zeroconf_module, "AsyncZeroconf", FakeZeroconf)
    with TemporaryDirectory() as directory:
        advertiser = zeroconf_module.ZeroconfAdvertiser(Path(directory), 8099)
        await advertiser.start()
        info = FakeZeroconf.instances[-1].registered[0]
        properties = {
            key.decode() if isinstance(key, bytes) else key: value.decode()
            if isinstance(value, bytes)
            else value
            for key, value in info.properties.items()
        }
        assert properties["api"] == "/api"
        assert "version" in properties and "instance_id" in properties
        assert "token" not in str(properties).lower()
        await advertiser.stop()
        assert FakeZeroconf.instances[-1].unregistered == [info]


@pytest.mark.asyncio
async def test_zeroconf_disabled_in_addon_mode(monkeypatch) -> None:
    monkeypatch.setattr(zeroconf_module, "AsyncZeroconf", FakeZeroconf)
    with TemporaryDirectory() as directory:
        advertiser = zeroconf_module.ZeroconfAdvertiser(Path(directory), 8099, enabled=False)
        await advertiser.start()
        assert advertiser._zeroconf is None


class FakeResponse:
    def raise_for_status(self) -> None:
        return


class FakeClient:
    calls: ClassVar[list[Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


@pytest.mark.asyncio
async def test_supervisor_discovery_payload_and_auth_header(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    FakeClient.calls = []
    assert await supervisor_module.register_supervisor_discovery(
        8099, addon_mode=True, client_factory=cast("Any", FakeClient)
    )
    url, kwargs = FakeClient.calls[0]
    assert url == "http://supervisor/discovery"
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert kwargs["json"] == {"service": "tonewatch", "config": {"host": "tonewatch", "port": 8099}}


@pytest.mark.asyncio
async def test_supervisor_discovery_retries_then_gives_up_nonfatally(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")

    class FailingClient(FakeClient):
        async def post(self, *_args, **_kwargs):
            raise OSError("offline")

    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    assert not await supervisor_module.register_supervisor_discovery(
        8099, addon_mode=True, client_factory=cast("Any", FailingClient), sleep=record_sleep
    )
    assert delays == [1, 2]


@pytest.mark.asyncio
async def test_supervisor_discovery_skipped_outside_addon_mode(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    assert not await supervisor_module.register_supervisor_discovery(
        8099, addon_mode=False, client_factory=cast("Any", FakeClient)
    )


def test_gen_api_is_deterministic() -> None:
    root = Path(__file__).parents[3]
    export_openapi = cast(
        "Any", runpy.run_path(str(root / "backend/scripts/export_openapi.py"))["main"]
    )
    generate_ws = cast(
        "Any", runpy.run_path(str(root / "backend/scripts/generate_ws_messages.py"))["main"]
    )

    export_openapi()
    generate_ws()
    first = [
        (root / "web/src/api/openapi.json").read_bytes(),
        (root / "web/src/api/ws-messages.ts").read_bytes(),
    ]
    export_openapi()
    generate_ws()
    second = [
        (root / "web/src/api/openapi.json").read_bytes(),
        (root / "web/src/api/ws-messages.ts").read_bytes(),
    ]
    assert first == second


def test_generated_files_use_lf() -> None:
    root = Path(__file__).parents[3]
    for path in (root / "web/src/api/openapi.json", root / "web/src/api/ws-messages.ts"):
        assert b"\r\n" not in path.read_bytes()
