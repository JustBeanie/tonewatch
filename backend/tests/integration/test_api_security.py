"""Named M5a security regression tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import httpx
import pytest
import structlog
from fastapi import Request

from tonewatch.api.app import create_app
from tonewatch.api.auth import AuthState
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import Call, Recording


def make_app(root: Path, **kwargs: Any):
    class FakeSupervisor:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def reload(self, _config: Any) -> None:
            pass

    return create_app(
        Settings(data_dir=root, **kwargs), supervisor=FakeSupervisor(), session_factory=FakeSession
    )


class FakeResult:
    def all(self) -> list[Any]:
        return []


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *_args: Any) -> None:
        return None

    async def scalars(self, *_args: Any) -> FakeResult:
        return FakeResult()


async def request(
    app: Any,
    method: str,
    path: str,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs: Any,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=transport or httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_every_api_route_requires_auth() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        for route in app.routes:
            path_template = getattr(route, "path", "")
            if not path_template.startswith("/api/") or path_template == "/api/auth/login":
                continue
            path = (
                path_template.replace("{item_id}", "missing")
                .replace("{call_id}", str(uuid4()))
                .replace("{recording_id}", "1")
            )
            method = next(iter(route.methods - {"HEAD"}))
            response = await request(app, method, path)
            assert response.status_code == 401, (method, path, response.text)


@pytest.mark.asyncio
async def test_wrong_bearer_token_rejected() -> None:
    with TemporaryDirectory() as directory:
        response = await request(
            make_app(Path(directory)),
            "GET",
            "/api/calls",
            headers={"Authorization": "Bearer wrong"},
        )
        assert response.status_code == 401


def test_token_compared_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as directory:
        settings = Settings(data_dir=Path(directory))
        state = AuthState(settings)
        calls: list[tuple[str, str]] = []

        def compare(a: str, b: str) -> bool:
            calls.append((a, b))
            return False

        monkeypatch.setattr("tonewatch.api.auth.hmac.compare_digest", compare)
        assert not state.bearer_valid(
            Request({"type": "http", "headers": [(b"authorization", b"Bearer x")]})
        )
        assert calls


def test_token_rotate_invalidates_old_token() -> None:
    with TemporaryDirectory() as directory:
        from tonewatch.api.auth import read_or_create_token, rotate_token

        settings = Settings(data_dir=Path(directory))
        old = read_or_create_token(settings)
        new = rotate_token(settings)
        assert new != old
        assert not AuthState(settings).bearer_valid(
            Request({"type": "http", "headers": [(b"authorization", f"Bearer {old}".encode())]})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addon,peer,ingress,forwarded,expected",
    [
        (True, "172.30.32.2", "/ha", None, 200),
        (True, "10.0.0.1", "/ha", None, 401),
        (False, "172.30.32.2", "/ha", None, 401),
        (True, "10.0.0.1", "/ha", "172.30.32.2", 401),
    ],
)
async def test_ingress_trusted_only_in_addon_mode_from_supervisor_ip(
    addon: bool, peer: str, ingress: str, forwarded: str | None, expected: int
) -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory), addon_mode=addon)
        headers = {"X-Ingress-Path": ingress}
        if forwarded:
            headers["X-Forwarded-For"] = forwarded
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 1)), base_url="http://test"
        ) as client:
            assert (await client.get("/api/tonesets", headers=headers)).status_code == expected


@pytest.mark.asyncio
async def test_ingress_base_path_applied_to_generated_urls() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        engine, sessions = create_database(f"sqlite+aiosqlite:///{root / 'api.db'}")
        await create_database_schema(engine)
        call_id = uuid4()
        recording_path = root / "recordings" / "call.mp3"
        recording_path.parent.mkdir()
        recording_path.write_bytes(b"recording")
        async with sessions() as session:
            session.add(
                Call(
                    id=call_id,
                    started_at=__import__("datetime").datetime.now(),
                    source_id="radio",
                    status="closed",
                )
            )
            session.add(
                Recording(
                    call_id=call_id,
                    format="mp3",
                    path=str(recording_path),
                    duration_s=1,
                    size_bytes=9,
                )
            )
            await session.commit()
        app = create_app(Settings(data_dir=root, addon_mode=True), session_factory=sessions)
        ingress_transport = httpx.ASGITransport(app=app, client=("172.30.32.2", 1))
        async with httpx.AsyncClient(transport=ingress_transport, base_url="http://test") as client:
            trusted = await client.get(
                f"/api/calls/{call_id}", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}
            )
        assert trusted.status_code == 200
        assert trusted.json()["recordings"][0]["url"].startswith(
            "/api/hassio_ingress/abc/api/recordings/"
        )
        token = (root / "api_token").read_text().strip()
        bearer = await request(
            app, "GET", f"/api/calls/{call_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert bearer.json()["recordings"][0]["url"].startswith("/api/recordings/")
        spoofed = await request(
            app,
            "GET",
            f"/api/calls/{call_id}",
            transport=httpx.ASGITransport(app=app, client=("10.0.0.1", 1)),
            headers={"Authorization": f"Bearer {token}", "X-Ingress-Path": "/evil"},
        )
        assert spoofed.json()["recordings"][0]["url"].startswith("/api/recordings/")
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_throttle_returns_429_with_retry_after() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory), ui_password="correct")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("10.0.0.2", 1)), base_url="http://test"
        ) as client:
            for _ in range(5):
                assert (
                    await client.post("/api/auth/login", json={"password": "wrong"})
                ).status_code == 401
            limited = await client.post("/api/auth/login", json={"password": "wrong"})
            assert limited.status_code == 429 and limited.headers["retry-after"]
        other = await request(app, "POST", "/api/auth/login", json={"password": "wrong"})
        assert other.status_code == 401


@pytest.mark.asyncio
async def test_session_cookie_flags() -> None:
    now = [1000.0]

    with TemporaryDirectory() as directory:
        app = create_app(
            Settings(data_dir=Path(directory), ui_password="correct"),
            clock=lambda: now[0],
            supervisor=object(),
            session_factory=FakeSession,
        )
        response = await request(app, "POST", "/api/auth/login", json={"password": "correct"})
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=43200" in cookie
        assert "Secure" not in cookie
        await request(app, "GET", "/api/calls", headers={"Cookie": cookie.split(";", 1)[0]})
        now[0] += 12 * 3600 + 1
        expired = await request(
            app, "GET", "/api/calls", headers={"Cookie": cookie.split(";", 1)[0]}
        )
        assert expired.status_code == 401
        secure_app = make_app(Path(directory) / "secure", ui_password="correct")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=secure_app), base_url="https://test"
        ) as secure_client:
            secure = await secure_client.post("/api/auth/login", json={"password": "correct"})
        assert "Secure" in secure.headers["set-cookie"]


@pytest.mark.asyncio
async def test_csrf_required_for_cookie_state_changes() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory), ui_password="correct")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/api/auth/login", json={"password": "correct"})
            assert (await client.post("/api/auth/logout")).status_code == 403
            assert (
                await client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
            ).status_code == 403
            token = (Path(directory) / "api_token").read_text().strip()
            assert (
                await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
            ).status_code == 200


@pytest.mark.asyncio
async def test_logout_invalidates_session() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory), ui_password="correct")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post("/api/auth/login", json={"password": "correct"})
            csrf = login.json()["csrf_token"]
            assert (
                await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
            ).status_code == 200
            assert (await client.get("/api/calls")).status_code == 401


@pytest.mark.asyncio
async def test_security_headers_present() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        for response in [
            await request(app, "GET", "/healthz"),
            await request(app, "GET", "/api/calls"),
        ]:
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["x-frame-options"] == "SAMEORIGIN"
            assert response.headers["content-security-policy"] == (
                "default-src 'none'; frame-ancestors 'self'"
            )


@pytest.mark.asyncio
async def test_errors_do_not_leak_internals() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("secret exception C:\\private\\file.py")

        response = await request(app, "GET", "/boom")
        assert (
            response.status_code == 500
            and "traceback" not in response.text.lower()
            and "private" not in response.text
        )


@pytest.mark.asyncio
async def test_secrets_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory), ui_password="password-value")
        token = (Path(directory) / "api_token").read_text().strip()
        with structlog.testing.capture_logs() as events:
            failed = await request(app, "POST", "/api/auth/login", json={"password": "wrong"})
            login = await request(
                app, "POST", "/api/auth/login", json={"password": "password-value"}
            )
            await request(
                app,
                "GET",
                "/api/calls",
                headers={"Authorization": f"Bearer {token}", "Cookie": "secret-cookie"},
            )
            assert failed.status_code == 401 and login.status_code == 200
        output = capsys.readouterr().err
        assert (
            token not in output
            and "password-value" not in output
            and "secret-cookie" not in output
            and "Authorization" not in output
            and "Cookie" not in output
            and token not in str(events)
            and "password-value" not in str(events)
            and any(event.get("event") == "request" for event in events)
        )


@pytest.mark.asyncio
async def test_request_id_propagates_to_logs_and_header(capsys: pytest.CaptureFixture[str]) -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        response = await request(app, "GET", "/healthz", headers={"X-Request-ID": "req-test-123"})
        assert response.headers["x-request-id"] == "req-test-123"
        assert "req-test-123" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_no_cors_headers_by_default() -> None:
    with TemporaryDirectory() as directory:
        response = await request(make_app(Path(directory)), "GET", "/healthz")
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_readyz_503_until_ready_and_healthz_leaks_nothing() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        ready = await request(app, "GET", "/readyz")
        health = await request(app, "GET", "/healthz")
        assert ready.status_code == 503 and health.status_code == 200
        assert set(health.json()) == {"ok"}
