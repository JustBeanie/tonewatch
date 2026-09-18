"""M19d credential-management contracts (A--F)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select

from tonewatch.api.app import create_app
from tonewatch.api.routes.ws import _authorized
from tonewatch.config.models import AppConfig, FileSource, LiveStreamConfig
from tonewatch.logging import _redact
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import AuditEvent


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audits(sessions: Any) -> list[AuditEvent]:
    async with sessions() as session:
        return list((await session.scalars(select(AuditEvent))).all())


@pytest.mark.asyncio
async def test_m19d_a_token_rotation_grace_and_persistence(tmp_path: Path) -> None:
    now = [1000.0]
    settings = Settings(data_dir=tmp_path, zeroconf_enabled=False)
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(settings, clock=lambda: now[0], session_factory=sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        old = (tmp_path / "api_token").read_text().strip()
        response = await client.post(
            "/api/admin/credentials/api-token/rotate",
            json={"grace_seconds": 10},
            headers=_headers(old),
        )
        assert response.status_code == 200, response.text
        new = response.json()["token"]
        assert response.headers["cache-control"] == "no-store"
        assert (await client.get("/api/tonesets", headers=_headers(new))).status_code == 200
        assert (await client.get("/api/tonesets", headers=_headers(old))).status_code == 200
        now[0] = 1011.0
        assert (await client.get("/api/tonesets", headers=_headers(old))).status_code == 401
    now[0] = 1005.0
    restarted = create_app(settings, clock=lambda: now[0], session_factory=sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        assert (await client.get("/api/tonesets", headers=_headers(old))).status_code == 200
        now[0] = 1011.0
        assert (await client.get("/api/tonesets", headers=_headers(old))).status_code == 401
    audits = await _audits(sessions)
    assert audits
    assert old not in str(audits) and new not in str(audits)
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_a_double_rotation_replaces_previous_and_validates_grace(
    tmp_path: Path,
) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first_old = app.state.auth.token
        first = await client.post(
            "/api/admin/credentials/api-token/rotate",
            json={"grace_seconds": 60},
            headers=_headers(first_old),
        )
        second_old = first.json()["token"]
        second = await client.post(
            "/api/admin/credentials/api-token/rotate",
            json={"grace_seconds": 60},
            headers=_headers(second_old),
        )
        newest = second.json()["token"]
        assert (await client.get("/api/tonesets", headers=_headers(first_old))).status_code == 401
        assert (await client.get("/api/tonesets", headers=_headers(second_old))).status_code == 200
        assert (await client.get("/api/tonesets", headers=_headers(newest))).status_code == 200
        for invalid in (-1, 86401, True, "60"):
            response = await client.post(
                "/api/admin/credentials/api-token/rotate",
                json={"grace_seconds": invalid},
                headers=_headers(newest),
            )
            assert response.status_code == 422
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_b_live_secret_rotation_invalidates_urls_and_closes_listeners(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path, zeroconf_enabled=False)
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(settings, session_factory=sessions)
    app.state.config = AppConfig(
        sources=[FileSource(id="radio", name="Radio", path="radio.wav", live_stream_enabled=True)],
        live_stream=LiveStreamConfig(enabled=True),
    )
    token = (tmp_path / "api_token").read_text().strip()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        issued = await client.post("/api/sources/radio/live-url", headers=_headers(token))
        assert issued.status_code == 200
        live_token = issued.json()["url"].split("?t=", 1)[1]
        listener = app.state.live_hub.add_listener("radio")
        rotated = await client.post(
            "/api/admin/credentials/live-secret/rotate", headers=_headers(token)
        )
        assert rotated.json() == {"ok": True}
        assert listener.closed
        assert (await client.get(f"/api/sources/radio/live.mp3?t={live_token}")).status_code == 401
        fresh = await client.post("/api/sources/radio/live-url", headers=_headers(token))
        assert (await client.head(fresh.json()["url"])).status_code == 200
    assert any(row.event_type == "live_secret_rotated" for row in await _audits(sessions))
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_c_password_change_and_rate_limit(tmp_path: Path) -> None:
    password = "-".join(("old", "password"))
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(
        Settings(data_dir=tmp_path, ui_password=password, zeroconf_enabled=False),
        session_factory=sessions,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/api/auth/login", json={"password": "old-password"})
        csrf = first.json()["csrf_token"]
        other = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        other_login = await other.post("/api/auth/login", json={"password": "old-password"})
        assert other_login.status_code == 200
        change = "/api/admin/credentials/ui-password"
        bad = await client.post(
            change,
            json={"current_password": "wrong", "new_password": "new-password-123"},
            headers={"X-CSRF-Token": csrf},
        )
        assert bad.status_code == 403
        bad_audits = await _audits(sessions)
        assert any(row.event_type == "ui_password_change_failed" for row in bad_audits)
        assert "wrong" not in str(bad_audits) and "new-password-123" not in str(bad_audits)
        short = await client.post(
            change,
            json={"current_password": "old-password", "new_password": "short"},
            headers={"X-CSRF-Token": csrf},
        )
        assert short.status_code == 422
        good = await client.post(
            change,
            json={"current_password": "old-password", "new_password": "new-password-123"},
            headers={"X-CSRF-Token": csrf},
        )
        assert good.status_code == 200
        assert (await client.get("/api/tonesets")).status_code == 200
        assert (await other.get("/api/tonesets")).status_code == 401
        new_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        assert (
            await new_client.post("/api/auth/login", json={"password": "new-password-123"})
        ).status_code == 200
        for _ in range(4):
            await client.post(
                change,
                json={"current_password": "wrong", "new_password": "new-password-123"},
                headers={"X-CSRF-Token": csrf},
            )
        limited = await client.post(
            change,
            json={"current_password": "wrong", "new_password": "new-password-123"},
            headers={"X-CSRF-Token": csrf},
        )
        assert limited.status_code == 429
        correct_during_lockout = await client.post(
            change,
            json={"current_password": "new-password-123", "new_password": "another-password"},
            headers={"X-CSRF-Token": csrf},
        )
        assert correct_during_lockout.status_code == 429
        await other.aclose()
        await new_client.aclose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_d_revoke_all_keeps_bearer(tmp_path: Path) -> None:
    password = "-".join(("old", "password"))
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(
        Settings(data_dir=tmp_path, ui_password=password, zeroconf_enabled=False),
        session_factory=sessions,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await client.post("/api/auth/login", json={"password": "old-password"})
        csrf = login.json()["csrf_token"]
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.post(
            "/api/admin/credentials/sessions/revoke-all", headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        assert (await client.get("/api/tonesets")).status_code == 401
        assert (await client.get("/api/tonesets", headers=_headers(token))).status_code == 200
    assert any(row.event_type == "sessions_revoked" for row in await _audits(sessions))
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_e_credential_auth_matrix(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        ui_password="matrix-password",  # noqa: S106 -- invented test credential.
        zeroconf_enabled=True,
        addon_mode=True,
    )
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(settings, session_factory=sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoints = [
            ("/api/admin/credentials/api-token/rotate", {"grace_seconds": 0}),
            ("/api/admin/credentials/live-secret/rotate", None),
            (
                "/api/admin/credentials/ui-password",
                {"current_password": "matrix-password", "new_password": "initial-password"},
            ),
            ("/api/admin/credentials/sessions/revoke-all", None),
        ]
        for path, body in endpoints:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as anonymous:
                assert (await anonymous.post(path, json=body)).status_code == 401
            session = await client.post("/api/auth/login", json={"password": "matrix-password"})
            assert session.status_code == 200
            cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
            request = client.build_request("POST", path, json=body, headers={"Cookie": cookie})
            assert (await client.send(request)).status_code == 403
            ingress = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("172.30.32.2", 1)),
                base_url="http://test",
            )
            assert (
                await ingress.post(
                    path, json=body, headers={"X-Ingress-Path": "/api/hassio_ingress/x"}
                )
            ).status_code == 403
            await ingress.aclose()
        token = app.state.auth.token
        for path, body in endpoints:
            response = await client.post(path, json=body, headers=_headers(token))
            assert response.status_code == 200
            if path.endswith("api-token/rotate"):
                token = response.json()["token"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19d_fix_legacy_rotation_is_csrf_protected(tmp_path: Path) -> None:
    app = create_app(
        Settings(data_dir=tmp_path, addon_mode=True, zeroconf_enabled=False),
        session_factory=lambda: None,
    )
    token = app.state.auth.token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("172.30.32.2", 1)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/auth/token/rotate",
            json={"grace_seconds": 0},
            headers={"Authorization": f"Bearer {token}", "X-Ingress-Path": "/api/hassio_ingress/x"},
        )
        assert response.status_code == 200
        ingress = await client.post(
            "/api/auth/token/rotate",
            json={"grace_seconds": 0},
            headers={"X-Ingress-Path": "/api/hassio_ingress/x"},
        )
        assert ingress.status_code == 403


def test_m19d_fix_token_matches_uses_constant_time_for_current_and_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=lambda: None
    )
    state = app.state.auth
    calls: list[tuple[str, str]] = []

    def compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr("tonewatch.api.auth.hmac.compare_digest", compare)
    assert state.token_matches(state.token)
    assert calls


def test_m19d_fix_log_redaction_tracks_rotated_tokens(tmp_path: Path) -> None:
    app = create_app(
        Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=lambda: None
    )
    state = app.state.auth
    old = state.token
    new, _ = state.rotate_api_token(60)
    event = {"message": f"{old} {new}"}
    redacted = _redact(None, "info", event)["message"]
    assert old not in redacted
    assert new not in redacted


def test_m19d_restart_mid_grace_still_redacts_previous_token(tmp_path: Path) -> None:
    now = [1000.0]
    settings = Settings(data_dir=tmp_path, zeroconf_enabled=False)
    app = create_app(settings, clock=lambda: now[0], session_factory=lambda: None)
    old = app.state.auth.token
    app.state.auth.rotate_api_token(60)
    create_app(settings, clock=lambda: now[0], session_factory=lambda: None)
    redacted = _redact(None, "info", {"message": f"leak {old}"})["message"]
    assert old not in redacted


@pytest.mark.asyncio
async def test_m19d_non_ascii_bearer_is_rejected_not_a_server_error(tmp_path: Path) -> None:
    app = create_app(
        Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=lambda: None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = [(b"authorization", "Bearer café".encode("latin-1"))]
        response = await client.get("/api/tonesets", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_m19d_fix_old_ws_subprotocol_token_expires(tmp_path: Path) -> None:
    now = [1000.0]
    settings = Settings(data_dir=tmp_path, zeroconf_enabled=False)
    app = create_app(settings, clock=lambda: now[0], session_factory=lambda: None)
    old = app.state.auth.token
    new, _ = app.state.auth.rotate_api_token(10)
    scope = {
        "type": "websocket",
        "scheme": "ws",
        "server": ("test", 80),
        "client": ("1", 1),
        "path": "/api/ws",
        "headers": [],
        "query_string": b"",
    }
    websocket = SimpleNamespace(
        app=app,
        scope=scope,
        headers={"sec-websocket-protocol": f"tonewatch.bearer.{old}"},
        url=SimpleNamespace(netloc="test:80"),
    )
    assert _authorized(cast("Any", websocket))[0]
    now[0] = 1011.0
    assert not _authorized(cast("Any", websocket))[0]
    assert new != old


@pytest.mark.asyncio
async def test_m19d_fix_bearer_can_set_initial_password_when_omitted(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=sessions)
    token = (tmp_path / "api_token").read_text().strip()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/admin/credentials/ui-password",
            json={"new_password": "initial-password"},
            headers=_headers(token),
        )
        assert response.status_code == 200
    await engine.dispose()
