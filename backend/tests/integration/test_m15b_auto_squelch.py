"""M15b auto-squelch configuration, diagnostics, and calibration contracts."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from sqlalchemy import select

from tonewatch.api.analyze import config_from_yaml
from tonewatch.api.app import create_app
from tonewatch.api.routes.config import CalibrateRequest, calibrate_squelch
from tonewatch.api.routes.ws import serialize_event
from tonewatch.config.models import AppConfig, SoundcardSource
from tonewatch.events import ChannelLevel
from tonewatch.settings import Settings
from tonewatch.storage.models import AuditEvent

if TYPE_CHECKING:
    from starlette.requests import Request


class FakeChannel:
    def __init__(self, levels: list[float]) -> None:
        self.levels = levels
        self.taps: set[Any] = set()

    def add_level_tap(self, tap: Any) -> None:
        self.taps.add(tap)
        for level in self.levels:
            tap(level)

    def remove_level_tap(self, tap: Any) -> None:
        self.taps.discard(tap)


class FakeSupervisor:
    def __init__(self, channel: FakeChannel | None) -> None:
        self.channel = channel

    def channel_for(self, _source_id: str) -> FakeChannel | None:
        return self.channel

    def source_status(self, _source_id: str) -> tuple[bool | None, str | None]:
        return True, None

    def source_diagnostics(self, _source_id: str) -> dict[str, object]:
        return {
            "squelch_mode_effective": "auto",
            "noise_floor_dbfs": -70.0,
            "open_dbfs_effective": -64.0,
            "close_dbfs_effective": -67.0,
            "calibrating": False,
            "stuck_open": False,
            "chatter": False,
            "transitions_per_min": 0.0,
        }

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_m15b_source_and_ws_diagnostics_are_complete() -> None:
    keys = {
        "squelch_mode_effective",
        "noise_floor_dbfs",
        "open_dbfs_effective",
        "close_dbfs_effective",
        "calibrating",
        "stuck_open",
        "chatter",
        "transitions_per_min",
    }
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        source = SoundcardSource(id="radio", name="Radio", device="default")
        app.state.config = AppConfig(sources=[source])
        token = (root / "api_token").read_text(encoding="ascii").strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            app.state.supervisor = None
            without = (await client.get("/api/sources", headers=headers)).json()[0]
            assert all(without[key] is None for key in keys)
            app.state.supervisor = FakeSupervisor(FakeChannel([-70.0]))
            listed = (await client.get("/api/sources", headers=headers)).json()[0]
            detail = (await client.get("/api/sources/radio", headers=headers)).json()
            assert keys <= listed.keys() and keys <= detail.keys()
            assert listed["squelch_mode_effective"] == "auto"
            assert detail["open_dbfs_effective"] == -64.0
        event = serialize_event(
            ChannelLevel(
                "radio",
                -70,
                0.1,
                __import__("datetime").datetime.now(),
                True,
                -30,
                "auto",
                -70,
                -64,
                -67,
                False,
                False,
                False,
                0.0,
            )
        )
        assert keys <= event["data"].keys()


@pytest.mark.asyncio
async def test_m15b_config_bounds_and_pre_m15b_yaml_fixture() -> None:
    fixture = """
sources:
  - id: radio
    name: Radio
    type: soundcard
    device: default
    squelch:
      mode: noise_floor
      floor_margin_db: 10
"""
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        fixture_path = Path(directory) / "pre-m15b.yaml"
        fixture_path.write_text(fixture, encoding="utf-8")
        config = config_from_yaml(fixture_path)
        assert config.sources[0].squelch.mode == "noise_floor"
        app = create_app(Settings(data_dir=Path(directory), zeroconf_enabled=False))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = (Path(directory) / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            base = {"id": "radio", "name": "Radio", "type": "soundcard", "device": "default"}
            too_short = {
                **base,
                "squelch": {"mode": "auto", "auto_min_samples_s": 31, "auto_window_s": 30},
            }
            bad_margin = {
                **base,
                "squelch": {"mode": "auto", "min_margin_db": 20, "max_margin_db": 10},
            }
            first = await client.post("/api/sources", json=too_short, headers=headers)
            second = await client.post("/api/sources", json=bad_margin, headers=headers)
            assert first.status_code == second.status_code == 422
            assert "auto_min_samples_s" in first.text
            assert "max_margin_db" in second.text


@pytest.mark.asyncio
async def test_m15b_calibrate_asgi_auth_audit_busy_and_tap_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        app = create_app(
            Settings(
                data_dir=root,
                ui_password="secret",  # noqa: S106 -- synthetic test credential
                zeroconf_enabled=False,
            )
        )
        source = SoundcardSource(id="radio", name="Radio", device="default")
        channel = FakeChannel([-70.0, -70.0, -60.0, -60.0])
        app.state.supervisor = FakeSupervisor(channel)
        async with app.router.lifespan_context(app):
            app.state.config = AppConfig(sources=[source])
            original_sleep = asyncio.sleep

            async def instant_sleep(_seconds: float) -> None:
                await original_sleep(0)

            monkeypatch.setattr("tonewatch.api.routes.config.asyncio.sleep", instant_sleep)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (
                    await client.post("/api/sources/radio/squelch/calibrate", json={"seconds": 5})
                ).status_code == 401
                token = (root / "api_token").read_text(encoding="ascii").strip()
                bearer = {"Authorization": f"Bearer {token}"}
                login = await client.post("/api/auth/login", json={"password": "secret"})
                assert login.status_code == 200
                assert (
                    await client.post("/api/sources/radio/squelch/calibrate", json={"seconds": 5})
                ).status_code == 403
                result = await client.post(
                    "/api/sources/radio/squelch/calibrate", json={"seconds": 5}, headers=bearer
                )
                assert result.status_code == 200
                body = result.json()
                assert body["floor_dbfs"] == -70.0
                assert body["spread_db"] == 0.0
                assert body["suggested"] == {
                    "mode": "level",
                    "open_dbfs": -64.0,
                    "close_dbfs": -67.0,
                }
                assert not channel.taps
                async with app.state.session_factory() as session:
                    rows = (
                        (
                            await session.execute(
                                select(AuditEvent).where(
                                    AuditEvent.event_type == "squelch_calibrated"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert len(rows) == 1
                repeat = await client.post(
                    "/api/sources/radio/squelch/calibrate", json={"seconds": 5}, headers=bearer
                )
                assert repeat.status_code == 200
                assert repeat.json()["suggested"] == body["suggested"]
                assert (
                    await client.post(
                        "/api/sources/missing/squelch/calibrate",
                        json={"seconds": 5},
                        headers=bearer,
                    )
                ).status_code == 404
                app.state.supervisor = FakeSupervisor(None)
                assert (
                    await client.post(
                        "/api/sources/radio/squelch/calibrate", json={"seconds": 5}, headers=bearer
                    )
                ).status_code == 409
                app.state.supervisor = FakeSupervisor(channel)
                for seconds in (4, 121):
                    assert (
                        await client.post(
                            "/api/sources/radio/squelch/calibrate",
                            json={"seconds": seconds},
                            headers=bearer,
                        )
                    ).status_code == 422
                app.state.squelch_calibrations = {"radio"}
                assert (
                    await client.post(
                        "/api/sources/radio/squelch/calibrate", json={"seconds": 5}, headers=bearer
                    )
                ).status_code == 429
            async with app.state.session_factory() as session:
                rows = (
                    (
                        await session.execute(
                            select(AuditEvent).where(AuditEvent.event_type == "squelch_calibrated")
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 2


@pytest.mark.asyncio
async def test_m15b_cancelled_calibration_removes_tap() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        source = SoundcardSource(id="radio", name="Radio", device="default")
        channel = FakeChannel([-70.0])
        app.state.supervisor = FakeSupervisor(channel)
        async with app.router.lifespan_context(app):
            app.state.config = AppConfig(sources=[source])
            task = asyncio.create_task(
                calibrate_squelch(
                    cast("Request", AnyRequest(app)), "radio", CalibrateRequest(seconds=5)
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not channel.taps


class AnyRequest:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.state = type("State", (), {"auth": "test"})()
