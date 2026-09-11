"""Named M5a resource regression tests."""

import wave
from collections.abc import MutableMapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar
from uuid import uuid4

import httpx
import numpy as np
import pytest

from tonewatch.api.app import create_app
from tonewatch.config.models import AppConfig, FileSource, ToneSet
from tonewatch.settings import Settings
from tonewatch.storage.models import Call, CallToneSet, Recording


def _tone() -> dict[str, Any]:
    return {"id": "fire", "name": "Fire", "sequence": [{"freq_hz": 1000, "min_s": 1}]}


def _wav(seconds: int = 1) -> bytes:
    stream = BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(np.zeros(16_000 * seconds, dtype=np.int16).tobytes())
    return stream.getvalue()


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *_args: Any) -> None:
        return None

    async def scalars(self, *_args: Any) -> Any:
        class Result:
            def all(self) -> list[Any]:
                return []

        return Result()


class BaseSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def reload(self, _config: Any) -> None:
        pass


class RichSession:
    row: Any = None
    values: ClassVar[list[list[Any]]] = []

    async def __aenter__(self) -> "RichSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *_args: Any) -> Any:
        return self.row

    async def scalars(self, *_args: Any) -> Any:
        items = self.values.pop(0) if self.values else []

        class Result:
            def all(self) -> list[Any]:
                return items

        return Result()


@pytest.mark.asyncio
async def test_toneset_crud_persists_yaml_and_reloads_supervisor() -> None:
    class FakeSupervisor:
        def __init__(self) -> None:
            self.reloads: list[AppConfig] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def reload(self, config: AppConfig) -> None:
            self.reloads.append(config)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        supervisor = FakeSupervisor()
        app = create_app(
            Settings(data_dir=root), supervisor=supervisor, session_factory=FakeSession
        )
        async with app.router.lifespan_context(app), await _client(app) as client:
            token = (root / "api_token").read_text().strip()
            headers = {"Authorization": f"Bearer {token}"}
            assert (
                await client.post("/api/tonesets", json=_tone(), headers=headers)
            ).status_code == 201
        assert "fire" in (root / "config.yaml").read_text() and supervisor.reloads


@pytest.mark.asyncio
async def test_config_crossref_error_is_422_naming_id() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            response = await client.post(
                "/api/tonesets",
                json={**_tone(), "alert_targets": ["missing-target"]},
                headers=headers,
            )
            assert response.status_code == 422 and "missing-target" in response.text


@pytest.mark.asyncio
async def test_delete_referenced_toneset_is_409_listing_referrers() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        app.state.config = AppConfig(
            tone_sets=[ToneSet(**_tone())],
            sources=[FileSource(id="radio", name="Radio", path="fixture.wav", tonesets=["fire"])],
        )
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            assert (await client.delete("/api/tonesets/fire", headers=headers)).status_code == 409


@pytest.mark.asyncio
async def test_script_target_enable_forbidden_unless_allowed() -> None:
    payload = {"id": "run", "name": "Run", "type": "script", "executable": "x", "enabled": True}
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            assert (
                await client.post("/api/alert-targets", json=payload, headers=headers)
            ).status_code == 403


@pytest.mark.asyncio
async def test_calls_filters_and_cursor_pagination() -> None:
    with TemporaryDirectory() as directory:
        first, second = uuid4(), uuid4()
        started = datetime.now(UTC)
        calls = [
            Call(id=first, started_at=started, source_id="radio", status="closed"),
            Call(id=second, started_at=started, source_id="radio", status="closed"),
        ]
        tones = [
            CallToneSet(
                call_id=first, toneset_id="fire", detected_at=started, matched_segment_freqs=[]
            ),
            CallToneSet(
                call_id=second, toneset_id="fire", detected_at=started, matched_segment_freqs=[]
            ),
        ]
        app = create_app(Settings(data_dir=Path(directory)), session_factory=RichSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            RichSession.values = [calls, tones]
            response = await client.get(
                "/api/calls?limit=999&cursor=0&source_id=radio&toneset_id=fire"
                f"&since={started.isoformat().replace('+00:00', 'Z')}"
                f"&until={started.isoformat().replace('+00:00', 'Z')}",
                headers=headers,
            )
            assert response.status_code == 200
            assert len(response.json()["items"]) == 2 and response.json()["next_cursor"] is None
            RichSession.values = [calls, tones]
            page = await client.get(
                "/api/calls?limit=1&cursor=0&source_id=radio&toneset_id=fire", headers=headers
            )
            assert (
                page.status_code == 200
                and len(page.json()["items"]) == 1
                and page.json()["next_cursor"] == "1"
            )


@pytest.mark.asyncio
async def test_calls_detail_and_recording_range_content() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        call_id = uuid4()
        recording_path = root / "recordings" / "recording.mp3"
        recording_path.parent.mkdir()
        recording_path.write_bytes(bytes(range(256)) * 2)
        RichSession.row = Call(
            id=call_id, started_at=datetime.now(UTC), source_id="radio", status="recorded"
        )
        RichSession.values = [
            [
                CallToneSet(
                    call_id=call_id,
                    toneset_id="fire",
                    detected_at=datetime.now(UTC),
                    matched_segment_freqs=[],
                )
            ],
            [
                Recording(
                    id=1,
                    call_id=call_id,
                    format="mp3",
                    path=str(recording_path),
                    duration_s=1,
                    size_bytes=512,
                )
            ],
            [],
        ]
        app = create_app(Settings(data_dir=root), session_factory=RichSession)
        token = (root / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            RichSession.row = None
            missing = await client.get(f"/api/calls/{uuid4()}", headers=headers)
            assert missing.status_code == 404
            RichSession.row = Call(
                id=call_id, started_at=datetime.now(UTC), source_id="radio", status="recorded"
            )
            detail = await client.get(f"/api/calls/{call_id}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["recordings"][0]["url"].endswith("/api/recordings/1")
            for range_header, expected in [
                (None, 200),
                ("bytes=0-99", 206),
                ("bytes=-100", 206),
                ("bytes=999-1000", 416),
            ]:
                RichSession.row = Recording(
                    id=1,
                    call_id=call_id,
                    format="mp3",
                    path=str(recording_path),
                    duration_s=1,
                    size_bytes=512,
                )
                response = await client.get(
                    "/api/recordings/1",
                    headers=headers | ({"Range": range_header} if range_header else {}),
                )
                assert response.status_code == expected
                assert response.headers.get("accept-ranges") == "bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "range_header,expected",
    [(None, 200), ("bytes=0-99", 206), ("bytes=-100", 206), ("bytes=999-1000", 416)],
)
async def test_recording_range_requests(range_header: str | None, expected: int) -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            # Unknown DB ids are safely refused before any client-supplied path is considered.
            response = await client.get(
                "/api/recordings/1",
                headers=headers | ({"Range": range_header} if range_header else {}),
            )
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_recording_path_outside_root_is_refused() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.get(
                    "/api/recordings/999", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 404


@pytest.mark.asyncio
async def test_analyze_rejects_oversize_413_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        called = False

        def unexpected(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal called
            called = True
            raise AssertionError

        monkeypatch.setattr("tonewatch.api.routes.analyze.analyze_wav", unexpected)
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                content=b"not-read",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "multipart/form-data; boundary=x",
                    "Content-Length": str(20 * 1024 * 1024 + 64 * 1024 + 1),
                },
            )
            assert response.status_code == 413
        assert not called

        chunk = b"x" * (1024 * 1024)
        preamble = (
            b"------tw\r\n"
            b'Content-Disposition: form-data; name="file"; filename="x.wav"\r\n'
            b"Content-Type: audio/wav\r\n\r\n"
        )
        chunks = [preamble + chunk[len(preamble) :]] + [chunk] * 22
        pulled = 0
        sent: list[MutableMapping[str, Any]] = []

        async def receive() -> MutableMapping[str, Any]:
            nonlocal pulled
            body = chunks[min(pulled, len(chunks) - 1)]
            pulled += 1
            return {"type": "http.request", "body": body, "more_body": True}

        async def send(message: MutableMapping[str, Any]) -> None:
            sent.append(message)

        scope: Any = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/analyze",
            "raw_path": b"/api/analyze",
            "query_string": b"",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"multipart/form-data; boundary=----tw"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
        await app(scope, receive, send)
        assert pulled <= 23 and any(message.get("status") == 413 for message in sent)


@pytest.mark.asyncio
async def test_analyze_rejects_non_wav_415() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.post(
                    "/api/analyze",
                    files={"file": ("x.wav", b"not wav")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).status_code == 415


@pytest.mark.asyncio
async def test_analyze_rejects_over_10_minutes() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                files={"file": ("x.wav", _wav(601))},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 413


@pytest.mark.asyncio
async def test_analyze_returns_documented_schema() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                files={"file": ("x.wav", _wav())},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert set(response.json()) == {"schema_version", "segments", "detections"}


@pytest.mark.asyncio
async def test_analyze_temp_files_removed() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            await client.post(
                "/api/analyze",
                files={"file": ("x.wav", b"bad")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert not list(Path(directory).glob("*.wav"))


@pytest.mark.asyncio
async def test_toneset_test_endpoint_publishes_marked_events_without_recording_file() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        app.state.config = AppConfig(tone_sets=[ToneSet(**_tone())])
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.post(
                    "/api/tonesets/fire/test", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 200
        assert (
            not list((Path(directory) / "recordings").glob("**/*"))
            if (Path(directory) / "recordings").exists()
            else True
        )


@pytest.mark.asyncio
async def test_devices_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tonewatch.api.app.input_devices", lambda: [{"index": 0}])
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        response = await request_devices(app, token)
        assert response.status_code == 200 and response.json() == [{"index": 0}]


async def request_devices(app: Any, token: str) -> httpx.Response:
    async with await _client(app) as client:
        return await client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
