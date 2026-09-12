"""S4 ASVS and STRIDE security regressions."""

import asyncio
import io
import ipaddress
import logging
import os
import shutil
import ssl
import subprocess
import threading
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import av
import httpx
import pytest
from fastapi import HTTPException
from pydantic import AnyUrl, ValidationError

import tonewatch.api.analyze as analyze_module
import tonewatch.sources.stream as stream_module
from tonewatch.__main__ import UVICORN_SECURITY_OPTIONS
from tonewatch.alerts.urlsafety import ResolvedURL, UnsafeURL, resolve_and_validate
from tonewatch.api.analyze import analyze_wav_with_timeout
from tonewatch.api.app import MAX_ANALYZE_BYTES, create_app
from tonewatch.api.audit import record_audit
from tonewatch.api.auth import AuthState, hash_password, verify_password
from tonewatch.api.deps import save_config
from tonewatch.config.models import AppConfig, FileSource, StreamSource, ToneSet, ToneSpec
from tonewatch.config.store import ConfigConflictError, ConfigStore
from tonewatch.events import FeedHealthChanged
from tonewatch.settings import Settings
from tonewatch.sources import soundcard as soundcard_module
from tonewatch.sources.base import SourceConfigError, SourceUnavailable
from tonewatch.sources.stream import StreamAudioSource, _decode_url


class FakeSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def reload(self, _config: Any) -> None:
        pass


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass


def _wav_payload() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 1600)
    return output.getvalue()


@contextmanager
def _http_server(handler: Callable[[Any], None]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self) -> None:
            handler(self)

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _https_server(handler: Callable[[Any], None]) -> Iterator[tuple[str, Path]]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required to create the local TLS verification fixture")
    with TemporaryDirectory() as directory:
        root = Path(directory)
        key = root / "key.pem"
        cert = root / "cert.pem"
        subprocess.run(  # noqa: S603 -- absolute openssl path and fixed test arguments.
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-nodes",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self) -> None:
                handler(self)

            def log_message(self, *_args: Any) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=cert, keyfile=key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"https://127.0.0.1:{server.server_port}", cert
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def _redirect(location: str) -> Callable[[Any], None]:
    def handler(request: Any) -> None:
        request.send_response(302)
        request.send_header("Location", location)
        request.send_header("Content-Length", "0")
        request.end_headers()

    return handler


def _audio_response(hits: list[int], hosts: list[str] | None = None) -> Callable[[Any], None]:
    payload = _wav_payload()

    def handler(request: Any) -> None:
        hits[0] += 1
        if hosts is not None:
            hosts.append(request.headers.get("Host", ""))
        request.send_response(200)
        request.send_header("Content-Type", "audio/wav")
        request.send_header("Content-Length", str(len(payload)))
        request.end_headers()
        request.wfile.write(payload)

    return handler


def _local_stream_policy(monkeypatch: pytest.MonkeyPatch, blocked_ports: set[int]) -> None:
    async def resolve_local(
        value: str | httpx.URL,
        *,
        schemes: frozenset[str],
        allow_private: bool = True,
        resolver: Any = None,
    ) -> ResolvedURL:
        del allow_private, resolver
        url = httpx.URL(value)
        if url.scheme not in schemes:
            raise UnsafeURL
        if url.port in blocked_ports:
            raise UnsafeURL
        return ResolvedURL(url, ipaddress.ip_address("127.0.0.1"))

    monkeypatch.setattr(stream_module, "resolve_and_validate", resolve_local)


def _app(root: Path, **kwargs: Any) -> Any:
    kwargs.setdefault("zeroconf_enabled", False)
    return create_app(
        Settings(data_dir=root, **kwargs),
        supervisor=FakeSupervisor(),
        session_factory=FakeSession,
    )


async def _request(app: Any, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path, **kwargs)


def test_file_scheme_exploit_regression() -> None:
    """Before S4, file URLs reached FFmpeg and could read api_token."""
    with TemporaryDirectory() as directory:
        settings = Settings(data_dir=Path(directory))
        (Path(directory) / "api_token").write_text("do-not-read\n", encoding="ascii")
        with pytest.raises(ValidationError):
            StreamSource(id="file", name="file", url=cast("Any", "file:///api_token"))
        config = type("Config", (), {"url": "file:///api_token"})()
        source = StreamAudioSource(cast("Any", config), settings=settings)
        with pytest.raises(SourceConfigError):
            asyncio.run(source.open())


def test_stream_rejects_file_concat_data_pipe_schemes() -> None:
    for scheme in ("file", "concat", "data", "pipe"):
        with pytest.raises(ValidationError):
            StreamSource(id="bad", name="bad", url=cast("Any", f"{scheme}:///secret"))

    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = (root / "api_token").read_text(encoding="ascii").strip()

        async def api_check() -> None:
            response = await _request(
                app,
                "POST",
                "/api/sources",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "id": "bad",
                    "name": "bad",
                    "type": "stream",
                    "url": "file:///secret",
                },
            )
            assert response.status_code == 422

        asyncio.run(api_check())

    async def run() -> None:
        config = type("Config", (), {"url": "file:///secret"})()
        source = StreamAudioSource(config)
        with pytest.raises(SourceConfigError):
            await source.open()

    asyncio.run(run())


def test_stream_protocol_whitelist_passed_to_pyav(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Container:
        streams: ClassVar[list[Any]] = []

        def __enter__(self) -> "Container":
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

    def fake_open(url: str, *, options: dict[str, str]) -> Container:
        seen.update(url=url, options=options)
        return Container()

    monkeypatch.setattr(stream_module.av, "open", fake_open)
    with pytest.raises(SourceUnavailable, match="no audio"):
        stream_module._decode_url("http://192.168.1.10/audio")
    assert seen["options"]["protocol_whitelist"] == "http,https,tcp,tls,rtsp,rtp,udp"
    assert seen["options"]["max_redirects"] == "0"


def test_stream_blocks_metadata_and_loopback_allows_lan() -> None:
    async def run() -> None:
        for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://2130706433/"):
            with pytest.raises(UnsafeURL):
                await resolve_and_validate(url, schemes=frozenset({"http"}))
        resolved = await resolve_and_validate("http://192.168.1.10/", schemes=frozenset({"http"}))
        assert str(resolved.address) == "192.168.1.10"
        with pytest.raises(UnsafeURL):
            await resolve_and_validate(
                "http://192.168.1.10/", schemes=frozenset({"http"}), allow_private=False
            )

    asyncio.run(run())


def test_ffmpeg_redirect_option_is_effective() -> None:
    target_hits = [0]
    with (
        _http_server(_audio_response(target_hits)) as target,
        _http_server(_redirect(target + "/audio")) as origin,
        pytest.raises((av.error.FFmpegError, OSError)),
    ):
        _decode_url(origin + "/audio")
    assert target_hits[0] == 0


def test_stream_redirect_to_blocked_host_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    target_hits = [0]
    with _http_server(_audio_response(target_hits)) as target:
        target_port = httpx.URL(target).port
        with _http_server(_redirect(target + "/audio")) as origin:
            _local_stream_policy(monkeypatch, {target_port or 0})
            config = StreamSource(id="radio", name="radio", url=AnyUrl(origin + "/audio"))
            source = StreamAudioSource(config, settings=Settings(data_dir=Path.cwd()))

            async def run() -> None:
                with pytest.raises((SourceConfigError, SourceUnavailable)):
                    await asyncio.wait_for(anext(source.__aiter__()), 2)

            asyncio.run(run())
    assert target_hits[0] == 0


def test_stream_redirect_to_allowed_host_followed_and_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_hits = [0]
    with (
        _http_server(_audio_response(target_hits)) as target,
        _http_server(_redirect(target + "/audio")) as origin,
    ):
        _local_stream_policy(monkeypatch, set())
        config = StreamSource(id="radio", name="radio", url=AnyUrl(origin + "/audio"))
        source = StreamAudioSource(config, settings=Settings(data_dir=Path.cwd()))

        async def run() -> None:
            await source.open()
            frame = await asyncio.wait_for(anext(source.__aiter__()), 5)
            assert frame.samples.size > 0
            await source.close()

        asyncio.run(run())
    assert target_hits[0] >= 1


def test_stream_sends_original_host_header() -> None:
    target_hits = [0]
    hosts: list[str] = []
    with _http_server(_audio_response(target_hits, hosts)) as server:
        _decode_url(server + "/audio")
        assert hosts[-1] == f"localhost:{httpx.URL(server).port}"


def test_stream_revalidates_dns_on_every_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def resolve(
        value: str | httpx.URL,
        *,
        schemes: frozenset[str],
        allow_private: bool = True,
        resolver: Any = None,
    ) -> ResolvedURL:
        del schemes, allow_private, resolver
        calls.append(str(value))
        if len(calls) == 1:
            return ResolvedURL(httpx.URL(value), ipaddress.ip_address("192.0.2.10"))
        raise UnsafeURL

    monkeypatch.setattr(stream_module, "resolve_and_validate", resolve)

    def fail_decode(_url: str) -> list[Any]:
        raise SourceUnavailable

    monkeypatch.setattr(stream_module, "_decode_url", fail_decode)
    source = StreamAudioSource(
        StreamSource(id="radio", name="radio", url=AnyUrl("rtsp://radio.example/stream")),
        sleep=lambda _delay: asyncio.sleep(0),
        jitter=lambda: 0,
    )

    async def run() -> None:
        with pytest.raises(SourceConfigError, match="unsafe stream URL"):
            await asyncio.wait_for(anext(source.__aiter__()), 2)

    asyncio.run(run())
    assert len(calls) >= 2


def test_stream_block_private_setting_reaches_running_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        ConfigStore(root).save(
            AppConfig(
                sources=[
                    StreamSource(id="radio", name="radio", url=AnyUrl("http://127.0.0.1/stream"))
                ]
            )
        )
        app = create_app(
            Settings(data_dir=root, stream_block_private=True, zeroconf_enabled=False),
            session_factory=FakeSession,
        )
        attempted = False

        def forbidden_open(*_args: Any, **_kwargs: Any) -> list[Any]:
            nonlocal attempted
            attempted = True
            raise AssertionError

        monkeypatch.setattr(stream_module.av, "open", forbidden_open)

        async def run() -> None:
            subscription = app.state.bus.subscribe(FeedHealthChanged)
            async with app.router.lifespan_context(app):
                for _ in range(3):
                    event = await asyncio.wait_for(subscription.__anext__(), 2)
                    if "unsafe stream URL" in event.reason:
                        break
                else:
                    pytest.fail("supervisor did not publish the unsafe URL failure")
                assert not event.healthy
            app.state.bus.unsubscribe(subscription)

        asyncio.run(run())
        assert not attempted


def test_ffmpeg_protocol_whitelist_blocks_file_read_even_if_validation_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "api_token"
        secret = b"api-token-secret"
        path.write_bytes(secret)
        file_url = f"file:{path.as_posix()}" if __import__("os").name == "nt" else path.as_uri()
        with av.open(file_url, format="data") as container:
            packet = next(packet for packet in container.demux() if packet.size)
            assert secret in bytes(packet)

        async def bypass_validation(
            value: str | httpx.URL,
            *,
            schemes: frozenset[str],
            allow_private: bool = True,
            resolver: Any = None,
        ) -> ResolvedURL:
            del schemes, allow_private, resolver
            return ResolvedURL(httpx.URL(value), ipaddress.ip_address("127.0.0.1"))

        monkeypatch.setattr(stream_module, "resolve_and_validate", bypass_validation)
        with pytest.raises(av.error.FFmpegError):
            _decode_url(file_url)


def test_stream_https_certificate_verification() -> None:
    """Verify TLS where the local PyAV backend can establish a TLS connection."""
    hits = [0]
    with _https_server(_audio_response(hits)) as (server, cert):
        try:
            av.open(server + "/audio", options={"tls_verify": "0"})
        except av.error.FFmpegError:
            pytest.skip(
                "local PyAV TLS probe unavailable (for example, the sandbox Windows user "
                "has no Schannel credentials)"
            )

        probe_hits = hits[0]
        assert probe_hits > 0
        with pytest.raises(av.error.FFmpegError):
            _decode_url(server + "/audio")
        assert hits[0] == probe_hits

        try:
            av.open(
                server + "/audio",
                options={"tls_verify": "1", "ca_file": str(cert)},
            )
        except av.error.FFmpegError:
            if os.name != "nt":
                raise
            logging.getLogger(__name__).info(
                "TLS backend ignores ca_file and uses the Windows certificate store"
            )
        else:
            if os.name == "nt":
                pytest.fail("Windows Schannel unexpectedly honored ca_file")
            logging.getLogger(__name__).info("TLS backend honored ca_file for the local fixture")


def test_tests_cannot_open_real_audio_devices() -> None:
    with pytest.raises(AssertionError):
        soundcard_module.sd.InputStream()


def test_rendered_log_output_redacts_secrets() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root, ui_password="password-value")  # noqa: S106 -- fake test credential.
        token = (root / "api_token").read_text(encoding="ascii").strip()
        stream = io.StringIO()
        for handler in logging.getLogger().handlers:
            cast("Any", handler).setStream(stream)

        async def run() -> None:
            assert (
                await _request(app, "POST", "/api/auth/login", json={"password": "wrong"})
            ).status_code == 401
            assert (
                await _request(app, "POST", "/api/auth/login", json={"password": "password-value"})
            ).status_code == 200
            headers = {"Authorization": f"Bearer {token}", "Cookie": "cookie-secret"}
            assert (await _request(app, "GET", "/api/config", headers=headers)).status_code == 200
            response = await _request(
                app,
                "POST",
                "/api/alert-targets",
                headers=headers,
                json={
                    "id": "hook",
                    "name": "hook",
                    "type": "webhook",
                    "url": "https://example.test",
                    "secret": "webhook-secret",
                },
            )
            assert response.status_code == 201

        asyncio.run(run())
        rendered = stream.getvalue()
        assert "[REDACTED]" in rendered
        assert all(
            secret not in rendered
            for secret in (token, "password-value", "cookie-secret", "webhook-secret")
        )


def test_analyze_chunked_body_rejected_after_limit_without_reading_rest() -> None:
    with TemporaryDirectory() as directory:
        app = _app(Path(directory))
        messages = [
            {"type": "http.request", "body": b"x" * (MAX_ANALYZE_BYTES + 1), "more_body": True},
            {"type": "http.request", "body": b"secret-rest", "more_body": False},
        ]
        pulls = 0
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            nonlocal pulls
            pulls += 1
            return messages[pulls - 1]

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/analyze",
            "raw_path": b"/api/analyze",
            "query_string": b"",
            "headers": [(b"content-type", b"application/octet-stream")],
            "client": ("198.51.100.10", 1234),
            "server": ("test", 80),
        }
        asyncio.run(app(scope, receive, send))
        assert pulls == 1
        assert sent[0]["status"] == 413


def test_token_file_permissions_enforced() -> None:
    if __import__("os").name == "nt":
        pytest.skip(
            "POSIX mode bits are unavailable on Windows; "
            "Windows ACL is documented as an accepted risk"
        )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "api_token"
        path.write_text("token\n", encoding="ascii")
        path.chmod(0o644)
        AuthState(Settings(data_dir=root))
        assert path.stat().st_mode & 0o777 == 0o600


def test_auth_secret_file_read_and_password_parser_fail_closed() -> None:
    assert verify_password("password", "not-a-scrypt-record") is False
    with TemporaryDirectory() as directory:
        root = Path(directory)
        password_hash = hash_password("password")
        (root / "ui_password").write_text(password_hash + "\n", encoding="ascii")
        state = AuthState(Settings(data_dir=root))
        assert state.password_hash == password_hash


def test_auth_routes_cover_status_logout_and_token_rotation() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root, ui_password="password")  # noqa: S106 -- fake test credential.
        token = (root / "api_token").read_text(encoding="ascii").strip()

        async def run() -> None:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/api/auth/status")).json()["via"] == "none"
                assert (
                    await client.get(
                        "/api/auth/status",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                ).json()["via"] == "bearer"
                assert (await client.post("/api/auth/login", json={})).status_code == 422
                login = await client.post("/api/auth/login", json={"password": "password"})
                assert login.status_code == 200
                client.cookies.update(login.cookies)
                assert (await client.get("/api/auth/status")).json()["via"] == "session"
                assert (
                    await client.post(
                        "/api/auth/logout",
                        headers={"X-CSRF-Token": login.json()["csrf_token"]},
                    )
                ).status_code == 200
                assert (
                    await client.post(
                        "/api/auth/token/rotate",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                ).status_code == 200
            assert (root / "api_token").read_text(encoding="ascii").strip() != token

        asyncio.run(run())


def test_config_dependency_returns_validation_and_conflict_errors() -> None:
    class Store:
        async def save_async(self, _config: AppConfig, **_kwargs: Any) -> None:
            raise ConfigConflictError("stale")

    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth="bearer"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=AppConfig(),
                store=Store(),
                supervisor=FakeSupervisor(),
                session_factory=None,
            )
        ),
    )

    fake_request = cast("Any", request)

    async def run() -> None:
        with pytest.raises(HTTPException) as validation:
            await save_config(fake_request, cast("Any", {"sources": "not-a-list"}))
        assert validation.value.status_code == 422
        with pytest.raises(HTTPException) as conflict:
            await save_config(fake_request, AppConfig())
        assert conflict.value.status_code == 412

    asyncio.run(run())


def test_audit_endpoint_is_authenticated_and_paginated() -> None:
    class Result:
        def all(self) -> list[Any]:
            return [
                SimpleNamespace(
                    id=2,
                    created_at=datetime.now(UTC),
                    actor="bearer",
                    event_type="config_change",
                    resource="config",
                    before={"secret": "[REDACTED]"},
                    after={},
                    details={},
                ),
                SimpleNamespace(
                    id=1,
                    created_at=datetime.now(UTC),
                    actor="anonymous",
                    event_type="login_failure",
                    resource="auth",
                    before=None,
                    after=None,
                    details={"status": 401},
                ),
            ]

    class AuditSession:
        async def __aenter__(self) -> "AuditSession":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            pass

        async def scalars(self, _query: Any) -> Result:
            return Result()

    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        app.state.session_factory = AuditSession
        token = (root / "api_token").read_text(encoding="ascii").strip()

        async def run() -> None:
            response = await _request(
                app,
                "GET",
                "/api/audit?limit=1",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert len(response.json()["items"]) == 1
            assert response.json()["next_cursor"] == "1"

        asyncio.run(run())


def test_configuration_routes_return_safe_validation_errors() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = (root / "api_token").read_text(encoding="ascii").strip()
        headers = {"Authorization": f"Bearer {token}"}
        tone = {
            "id": "tone",
            "name": "tone",
            "sequence": [{"freq_hz": 500, "min_s": 1}],
        }

        async def run() -> None:
            put_config = await _request(app, "PUT", "/api/config", headers=headers, json={})
            assert put_config.status_code == 200
            assert put_config.headers["etag"]
            assert (
                await _request(app, "GET", "/api/tonesets/missing", headers=headers)
            ).status_code == 404
            assert (
                await _request(
                    app, "PUT", "/api/tonesets/path", headers=headers, json={**tone, "id": "other"}
                )
            ).status_code == 422
            assert (
                await _request(app, "GET", "/api/sources/missing", headers=headers)
            ).status_code == 404
            assert (
                await _request(
                    app, "PUT", "/api/sources/path", headers=headers, json={"id": "other"}
                )
            ).status_code == 422
            assert (
                await _request(
                    app,
                    "PUT",
                    "/api/alert-targets/hook",
                    headers=headers,
                    json={"id": "hook", "type": "webhook"},
                )
            ).status_code == 422
            assert (
                await _request(
                    app,
                    "POST",
                    "/api/alert-targets",
                    headers=headers,
                    json={
                        "id": "script",
                        "name": "script",
                        "type": "script",
                        "executable": "echo",
                        "enabled": True,
                    },
                )
            ).status_code == 403
            assert (
                await _request(app, "DELETE", "/api/sources/missing", headers=headers)
            ).status_code == 404
            assert (
                await _request(app, "POST", "/api/tonesets/missing/test", headers=headers)
            ).status_code == 404

        asyncio.run(run())


def test_config_writers_use_optimistic_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.save(AppConfig())
            revision = store.etag()
            first = AppConfig(
                tone_sets=[ToneSet(id="a", name="a", sequence=[ToneSpec(freq_hz=500, min_s=1)])]
            )
            second = AppConfig(
                tone_sets=[ToneSet(id="b", name="b", sequence=[ToneSpec(freq_hz=600, min_s=1)])]
            )
            await store.save_async(first, expected_etag=revision)
            with pytest.raises(ConfigConflictError):
                await store.save_async(second, expected_etag=revision)
            assert store.load() == first

    asyncio.run(run())


def test_slow_loris_server_limits_are_declared() -> None:
    assert UVICORN_SECURITY_OPTIONS == {
        "timeout_keep_alive": 5,
        "h11_max_incomplete_event_size": 64 * 1024,
        "limit_concurrency": 100,
    }


def test_resource_caps_reject_excess_configuration() -> None:
    tone = ToneSet(id="tone", name="tone", sequence=[ToneSpec(freq_hz=500, min_s=1)])
    with pytest.raises(ValidationError):
        AppConfig(tone_sets=[tone] * 501)
    sources = [FileSource(id=f"s{index}", name="source", path="x.wav") for index in range(17)]
    with pytest.raises(ValidationError):
        AppConfig(sources=cast("Any", sources))


def test_login_throttle_state_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as directory:
        state = AuthState(
            Settings(data_dir=Path(directory), ui_password="secret")  # noqa: S106 -- fake test credential.
        )
        monkeypatch.setattr("tonewatch.api.auth.verify_password", lambda *_args: False)
        for index in range(1100):
            with pytest.raises(HTTPException):
                state.check_login(f"spoofed-{index}", "wrong")
        assert len(state.failures) <= 1024


def test_upload_decode_timeout() -> None:
    def slow(*_args: Any) -> dict[str, Any]:
        time.sleep(1)
        return {}

    original = analyze_module.analyze_wav
    analyze_module.analyze_wav = cast("Any", slow)
    try:
        with pytest.raises(ValueError, match="timed out"):
            asyncio.run(analyze_wav_with_timeout(Path("unused.wav"), AppConfig(), timeout_s=0.01))
    finally:
        analyze_module.analyze_wav = original


def test_audit_events_are_recorded_and_secrets_masked() -> None:
    class Session:
        rows: ClassVar[list[Any]] = []

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            pass

        def add(self, row: Any) -> None:
            self.rows.append(row)

        async def commit(self) -> None:
            pass

    async def run() -> None:
        factory = Session
        for event_type in (
            "config_change",
            "test_trigger",
            "token_rotation",
            "login_success",
            "login_failure",
        ):
            await record_audit(
                factory,
                actor="bearer",
                event_type=event_type,
                resource="test",
                before={"secret": "hidden"},
                after={"password": "hidden"},
            )
        assert {row.event_type for row in Session.rows} == {
            "config_change",
            "test_trigger",
            "token_rotation",
            "login_success",
            "login_failure",
        }
        assert Session.rows[0].before["secret"] == "[REDACTED]"  # noqa: S105 -- redaction assertion.
        assert Session.rows[0].after["password"] == "[REDACTED]"  # noqa: S105 -- redaction assertion.

    asyncio.run(run())
