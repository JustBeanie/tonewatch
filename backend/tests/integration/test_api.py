"""M5a API smoke and security contract tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import httpx
import pytest

from tonewatch.api.analyze import config_from_yaml
from tonewatch.api.app import create_app
from tonewatch.api.auth import hash_password, read_or_create_token, rotate_token, verify_password
from tonewatch.config.models import AppConfig, FileSource
from tonewatch.settings import Settings
from tonewatch.sources import soundcard as soundcard_module


@pytest.mark.asyncio
async def test_api_auth_crud_headers_and_token() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/readyz")).status_code == 200
            status = await client.get("/api/auth/status")
            assert status.json() == {
                "authenticated": False,
                "password_required": False,
                "via": "none",
            }
            response = await client.get("/api/tonesets")
            assert response.status_code == 401
            token = (root / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get("/api/tonesets", headers=headers)
            assert response.status_code == 200
            assert (await client.get("/api/auth/status", headers=headers)).json()["via"] == "bearer"
            assert response.headers["x-content-type-options"] == "nosniff"
            tone = {
                "id": "fire",
                "name": "Fire",
                "sequence": [{"freq_hz": 1000, "min_s": 1}],
            }
            assert (
                await client.post("/api/tonesets", json=tone, headers=headers)
            ).status_code == 201
            assert (await client.get("/api/tonesets/fire", headers=headers)).status_code == 200
            assert (
                await client.put(
                    "/api/tonesets/fire", json={**tone, "name": "Updated"}, headers=headers
                )
            ).status_code == 200
            assert (
                await client.post("/api/tonesets/fire/test", headers=headers)
            ).status_code == 200
            assert (await client.delete("/api/tonesets/fire", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_wrong_token_and_missing_csrf() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        app = create_app(
            Settings(data_dir=Path(directory), ui_password="secret", zeroconf_enabled=False),
            session_factory=cast("Any", lambda: None),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (
                await client.get("/api/calls", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401
            login = await client.post("/api/auth/login", json={"password": "secret"})
            assert login.status_code == 200
            assert (await client.post("/api/auth/logout")).status_code == 403
            csrf = login.json()["csrf_token"]
            assert (
                await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
            ).status_code == 200


@pytest.mark.asyncio
async def test_api_resources_and_rejections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_open(source: Any) -> None:
        source._closed = False

    monkeypatch.setattr(soundcard_module.SoundcardSource, "open", fake_open)
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            source = {
                "id": "radio",
                "name": "Radio",
                "type": "soundcard",
                "device": 0,
            }
            target = {"id": "mqtt", "name": "MQTT", "type": "mqtt"}
            assert (
                await client.post("/api/sources", json=source, headers=headers)
            ).status_code == 201
            assert (await client.get("/api/sources/radio", headers=headers)).status_code == 200
            assert (
                await client.put(
                    "/api/sources/radio", json={**source, "name": "R"}, headers=headers
                )
            ).status_code == 200
            assert (await client.delete("/api/sources/radio", headers=headers)).status_code == 200
            assert (
                await client.post("/api/alert-targets", json=target, headers=headers)
            ).status_code == 201
            assert (await client.get("/api/alert-targets", headers=headers)).status_code == 200
            assert (await client.get("/api/calls", headers=headers)).status_code == 200
            assert (
                await client.post(
                    "/api/analyze",
                    files={"file": ("x.txt", b"no", "text/plain")},
                    headers=headers,
                )
            ).status_code == 415
            assert (await client.get("/api/recordings/999", headers=headers)).status_code == 404
            script = {
                "id": "run",
                "name": "Run",
                "type": "script",
                "executable": "x",
                "enabled": True,
            }
            assert (
                await client.post("/api/alert-targets", json=script, headers=headers)
            ).status_code == 403


def test_auth_and_analyze_helpers() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = Settings(data_dir=root, zeroconf_enabled=False)
        first = read_or_create_token(settings)
        assert first == read_or_create_token(settings)
        assert rotate_token(settings) != first
        encoded = hash_password("secret")
        assert verify_password("secret", encoded)
        assert not verify_password("wrong", encoded)
        config_path = root / "config.yaml"
        config_path.write_text("{}\n", encoding="utf-8")
        assert config_from_yaml(config_path).tone_sets == []


@pytest.mark.asyncio
async def test_source_status_is_null_without_supervisor_and_live_when_running() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = Settings(data_dir=root, zeroconf_enabled=False)
        source = FileSource(id="radio", name="Radio", path="radio.wav")
        app = create_app(settings)
        app.state.config = AppConfig(sources=[source])
        token = (root / "api_token").read_text(encoding="ascii").strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            listed = await client.get("/api/sources", headers=headers)
            detail = await client.get("/api/sources/radio", headers=headers)
        assert listed.status_code == detail.status_code == 200
        assert listed.json()[0]["squelch_open"] is None
        assert listed.json()[0]["last_activity_at"] is None
        assert detail.json()["squelch_open"] is None
        assert detail.json()["last_activity_at"] is None

        class RunningSupervisor:
            def source_status(self, source_id: str) -> tuple[bool, str]:
                assert source_id == "radio"
                return True, "2026-01-01T00:00:01+00:00"

        live_app = create_app(settings, supervisor=RunningSupervisor())
        live_app.state.config = AppConfig(sources=[source])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=live_app), base_url="http://test"
        ) as client:
            live = await client.get("/api/sources/radio", headers=headers)
        assert live.json()["squelch_open"] is True
        assert live.json()["last_activity_at"] == "2026-01-01T00:00:01+00:00"
