"""M14a live restream API and MP3 integration coverage."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast

import av
import httpx
import numpy as np
import pytest
import structlog
from starlette.requests import Request

from tonewatch.api.app import create_app
from tonewatch.api.routes.live import live_mp3
from tonewatch.config.models import AppConfig, FileSource, LiveStreamConfig
from tonewatch.logging import configure_logging
from tonewatch.settings import Settings
from tonewatch.streaming import live as live_module
from tonewatch.streaming.live import LiveHub, make_live_token, verify_live_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class NoopSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def _app(root: Path, *, enabled: bool = True, public_base_url: str | None = None) -> Any:
    app = create_app(
        Settings(data_dir=root, zeroconf_enabled=False, public_base_url=public_base_url),
        supervisor=NoopSupervisor(),
        session_factory=lambda: None,
    )
    app.state.config = AppConfig(
        sources=[FileSource(id="radio", name="Radio", path="fixture.wav")],
        live_stream=LiveStreamConfig(
            enabled=enabled, max_listeners_per_source=2, max_listeners_total=3
        ),
    )
    return app


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_live_url_and_invalid_token_cases(capsys: pytest.CaptureFixture[str]) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        async with await _client(app) as client:
            bearer = {"Authorization": f"Bearer {app.state.auth.token}"}
            issued = await client.post("/api/sources/radio/live-url", headers=bearer)
            assert issued.status_code == 200
            token = issued.json()["url"].split("t=", 1)[1]
            expires_at = datetime.fromisoformat(issued.json()["expires_at"])
            assert expires_at > datetime.now(UTC)
            assert issued.json()["url"].startswith("/api/sources/radio/live.mp3?t=")
            app.state.settings.public_base_url = "https://example.test/tonewatch"
            external = await client.post(
                "/api/sources/radio/live-url?external=true", headers=bearer
            )
            assert external.json()["url"].startswith(
                "https://example.test/tonewatch/api/sources/radio/live.mp3?t="
            )
            assert "live_url_issued" not in capsys.readouterr().out
            assert (await client.get("/api/sources/radio/live.mp3")).status_code == 401
            for value in ("missing", token[:-1] + "x"):
                response = await client.get(f"/api/sources/radio/live.mp3?t={value}")
                assert response.status_code == 401
            expired = make_live_token(root, "radio", int(time.time()) - 1)
            assert (await client.get(f"/api/sources/radio/live.mp3?t={expired}")).status_code == 401
            assert (await client.get(f"/api/sources/other/live.mp3?t={token}")).status_code == 404
            logs = capsys.readouterr().out
            assert token not in logs


@pytest.mark.asyncio
async def test_live_get_ignores_range_and_returns_mp3(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"mp3"]

        def close(self) -> None:
            pass

    monkeypatch.setattr(live_module, "_Mp3Encoder", Encoder)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = make_live_token(root, "radio", int(time.time()) + 3600)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request"}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/sources/radio/live.mp3",
                "query_string": f"t={token}".encode(),
                "headers": [(b"range", b"bytes=0-")],
                "app": app,
            },
            receive,
        )
        response = await live_mp3(request, "radio", token)
        assert response.status_code == 200
        listener = next(iter(app.state.live_hub._streams["radio"].listeners))
        listener.queue.put_nowait(b"mp3")
        iterator = cast("AsyncIterator[bytes]", cast("Any", response).body_iterator)
        assert await iterator.__anext__() == b"mp3"
        await cast("Any", iterator).aclose()


@pytest.mark.asyncio
async def test_live_head_has_headers_without_listener() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = make_live_token(root, "radio", int(time.time()) + 3600)
        async with await _client(app) as client:
            response = await client.head(f"/api/sources/radio/live.mp3?t={token}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["accept-ranges"] == "none"
        assert response.content == b""
        assert app.state.live_hub.listener_count == 0


def test_live_access_and_request_logs_redact_query_token(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    value = "v1.2000000000.nonce.signature"
    configure_logging("INFO", json=True)
    access = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO):
        access.info('127.0.0.1:1 - "GET /api/sources/x/live.mp3?t=%s HTTP/1.1" 200', value)
        structlog.get_logger("tonewatch.api").info(
            "request", path=f"/api/sources/x/live.mp3?t={value}"
        )
    output = capsys.readouterr().err
    assert '"GET /api/sources/x/live.mp3' in output
    assert value not in output


@pytest.mark.asyncio
async def test_live_disabled_and_caps_return_expected_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"mp3"]

        def close(self) -> None:
            pass

    monkeypatch.setattr(live_module, "_Mp3Encoder", Encoder)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        async with await _client(app) as client:
            token = app.state.auth.token
            headers = {"Authorization": f"Bearer {token}"}
            first = app.state.live_hub.add_listener("radio")
            second = app.state.live_hub.add_listener("radio")
            assert (
                await client.get("/api/sources/radio/live.mp3", headers=headers)
            ).status_code == 503
            app.state.live_hub.remove_listener(first)
            app.state.live_hub.remove_listener(second)
            app.state.live_hub.add_listener("one")
            app.state.live_hub.add_listener("two")
            app.state.live_hub.add_listener("three")
            assert (
                await client.post("/api/sources/radio/live-url", headers=headers)
            ).status_code == 503
        disabled = _app(root, enabled=False)
        async with await _client(disabled) as client:
            assert (await client.get("/api/sources/radio/live.mp3")).status_code == 404
            assert (
                await client.post(
                    "/api/sources/radio/live-url",
                    headers={"Authorization": f"Bearer {disabled.state.auth.token}"},
                )
            ).status_code == 404


@pytest.mark.asyncio
async def test_successful_live_response_has_stream_headers_and_removes_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"mp3"]

        def close(self) -> None:
            pass

    monkeypatch.setattr(live_module, "_Mp3Encoder", Encoder)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = make_live_token(root, "radio", int(time.time()) + 3600)
        messages = iter(({"type": "http.request"}, {"type": "http.disconnect"}))

        async def receive() -> dict[str, Any]:
            return next(messages)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/sources/radio/live.mp3",
                "query_string": f"t={token}".encode(),
                "headers": [],
                "app": app,
            },
            receive,
        )
        response = await live_mp3(request, "radio", token)
        assert response.media_type == "audio/mpeg"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["accept-ranges"] == "none"
        listener = next(iter(app.state.live_hub._streams["radio"].listeners))
        listener.queue.put_nowait(b"mp3")
        iterator = cast("AsyncIterator[bytes]", cast("Any", response).body_iterator)
        assert await iterator.__anext__() == b"mp3"
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()
        assert app.state.live_hub.listener_count == 0


@pytest.mark.asyncio
async def test_server_removed_live_response_iterator_finishes(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"mp3"]

        def close(self) -> None:
            pass

    monkeypatch.setattr(live_module, "_Mp3Encoder", Encoder)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = _app(root)
        token = make_live_token(root, "radio", int(time.time()) + 3600)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request"}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/sources/radio/live.mp3",
                "query_string": f"t={token}".encode(),
                "headers": [],
                "app": app,
            },
            receive,
        )
        response = await live_mp3(request, "radio", token)
        listener = next(iter(app.state.live_hub._streams["radio"].listeners))
        app.state.live_hub.remove_listener(listener)
        iterator = cast("AsyncIterator[bytes]", cast("Any", response).body_iterator)
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()


@pytest.mark.asyncio
async def test_file_source_two_listeners_decode_two_seconds_of_mp3() -> None:
    hub = LiveHub(queue_seconds=2.0)
    listeners = [hub.add_listener("radio"), hub.add_listener("radio")]
    samples = np.sin(np.arange(1600, dtype=np.float32) * (2 * np.pi * 1000 / 16_000))
    encoded = [bytearray(), bytearray()]
    for _ in range(30):
        hub.feed("radio", samples)
        for index, listener in enumerate(listeners):
            while not listener.queue.empty():
                encoded[index].extend(listener.queue.get_nowait())
    for stream in encoded:
        container = av.open(BytesIO(bytes(stream)), mode="r", format="mp3")
        decoded = sum(frame.samples for frame in container.decode(audio=0))
        container.close()
        assert decoded >= 2 * 44_100
    for listener in listeners:
        hub.remove_listener(listener)


def test_token_rotation_and_exact_source_scope() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        token = make_live_token(root, "radio", int(time.time()) + 3600)
        assert verify_live_token(root, "radio", token)
        assert not verify_live_token(root, "other", token)
        (root / "live_stream_secret").write_bytes(b"rotated")
        assert not verify_live_token(root, "radio", token)
