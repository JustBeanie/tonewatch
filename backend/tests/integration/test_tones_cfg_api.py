"""API contract tests for tones.cfg preview and apply."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from tonewatch.api.app import MAX_TONES_CFG_IMPORT_BYTES, create_app
from tonewatch.config.models import AppConfig, FileSource, MqttTarget, ToneSet, ToneSpec
from tonewatch.config.store import ConfigStore
from tonewatch.settings import Settings

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tones_cfg" / "synthetic.cfg"


@pytest.mark.parametrize(
    ("declared_length", "expected_status"),
    [("abc", 400), ("-5", 400), ("1.5", 400), ("", 400), (str(256 * 1024 + 1), 413)],
)
@pytest.mark.asyncio
async def test_tones_cfg_api_validates_content_length(
    declared_length: str, expected_status: int
) -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        ConfigStore(root).save(AppConfig())
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            response = await client.post(
                "/api/import/tones-cfg",
                content=b"[One]\nlongtone=1000\nlongtonelength=1\n",
                headers={"Authorization": f"Bearer {token}", "Content-Length": declared_length},
            )
            assert response.status_code == expected_status
            assert response.json()["detail"] == (
                "invalid Content-Length" if expected_status == 400 else "upload too large"
            )


async def _chunks(value: bytes):
    yield value


async def _three_chunks(*values: bytes):
    for value in values:
        yield value


def _oversized_synthetic_config() -> bytes:
    chunk = FIXTURE.read_text(encoding="utf-8-sig").encode()
    return chunk * ((300 * 1024 // len(chunk)) + 1)


@pytest.mark.asyncio
async def test_tones_cfg_api_auth_csrf_preview_apply_and_replace() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        store = ConfigStore(root)
        store.save(
            AppConfig(
                tone_sets=[
                    ToneSet(
                        id="existing",
                        name="Existing",
                        sequence=[ToneSpec(freq_hz=500, min_s=1)],
                    )
                ],
                sources=[FileSource(id="source", name="Source", path="source.wav")],
                alert_targets=[MqttTarget(id="target", name="Target")],
            )
        )
        credential = "password"
        app = create_app(Settings(data_dir=root, ui_password=credential, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            source_text = FIXTURE.read_text(encoding="utf-8-sig")
            assert (
                await client.post("/api/import/tones-cfg", content=source_text)
            ).status_code == 401
            login = await client.post("/api/auth/login", json={"password": credential})
            csrf = login.json()["csrf_token"]
            csrf_headers = {"X-CSRF-Token": csrf}
            assert (
                await client.post("/api/import/tones-cfg", content=source_text)
            ).status_code == 403
            preview = await client.post(
                "/api/import/tones-cfg", content=source_text, headers=csrf_headers
            )
            assert preview.status_code == 200
            assert preview.json()["applied"] is False
            assert len(store.load().tone_sets) == 1
            token = (root / "api_token").read_text(encoding="ascii").strip()
            bearer = {"Authorization": f"Bearer {token}"}
            streamed_preview = await client.post(
                "/api/import/tones-cfg",
                content=_chunks(source_text.encode()),
                headers={**bearer, "content-type": "text/plain"},
            )
            assert streamed_preview.status_code == 200
            streamed_too_large = await client.post(
                "/api/import/tones-cfg",
                content=_chunks(b"x" * (256 * 1024 + 1)),
                headers={**bearer, "content-type": "text/plain"},
            )
            assert streamed_too_large.status_code == 413
            too_large = await client.post(
                "/api/import/tones-cfg", content="x" * (256 * 1024 + 1), headers=bearer
            )
            assert too_large.status_code == 413
            applied = await client.post(
                "/api/import/tones-cfg?apply=true&mode=replace",
                files={"file": ("private-name.cfg", source_text, "text/plain")},
                headers=bearer,
            )
            assert applied.status_code == 200
            assert applied.json()["applied"] is True
            saved = store.load()
            assert len(saved.tone_sets) == 3
            assert saved.sources[0].id == "source"
            assert saved.alert_targets[0].id == "target"
            audit = await client.get("/api/audit", headers=bearer)
            audit_items = audit.json()["items"]
            import_events = [
                item for item in audit_items if item["event_type"] == "tones_cfg_import"
            ]
            assert import_events
            assert import_events[0]["before"] is None
            assert import_events[0]["after"] is None
            assert import_events[0]["details"] == {
                "imported": 3,
                "skipped": 2,
                "mode": "replace",
            }
            assert "@" not in audit.text


@pytest.mark.asyncio
async def test_tones_cfg_api_rejects_bad_utf8_and_missing_multipart_file() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        store = ConfigStore(root)
        store.save(AppConfig())
        credential = "password"
        app = create_app(Settings(data_dir=root, ui_password=credential, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            bearer = {"Authorization": f"Bearer {token}"}
            bad_utf8 = await client.post("/api/import/tones-cfg", content=b"\xff", headers=bearer)
            assert bad_utf8.status_code == 422
            missing_file = await client.post(
                "/api/import/tones-cfg",
                content=b"--boundary--",
                headers={
                    **bearer,
                    "content-type": "multipart/form-data; boundary=boundary",
                },
            )
            assert missing_file.status_code == 422
            failed_apply = await client.post(
                "/api/import/tones-cfg?apply=true",
                content="[Empty]\ndescription=Only notes\n",
                headers=bearer,
            )
            assert failed_apply.status_code == 200
            assert failed_apply.json()["applied"] is False


@pytest.mark.asyncio
async def test_streamed_oversized_apply_does_not_persist_raw_or_multipart() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        initial = AppConfig(
            tone_sets=[
                ToneSet(
                    id="keep",
                    name="Keep",
                    sequence=[ToneSpec(freq_hz=500, min_s=1)],
                )
            ],
            sources=[FileSource(id="source", name="Source", path="source.wav")],
            alert_targets=[MqttTarget(id="target", name="Target")],
        )
        store = ConfigStore(root)
        store.save(initial)
        before_yaml = (root / "config.yaml").read_bytes()
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            valid_config = FIXTURE.read_text(encoding="utf-8-sig").encode()
            headers = {"Authorization": f"Bearer {token}", "content-type": "text/plain"}
            raw = await client.post(
                "/api/import/tones-cfg?apply=true&mode=replace",
                content=_three_chunks(valid_config, b"\n", b"x" * (MAX_TONES_CFG_IMPORT_BYTES + 1)),
                headers=headers,
            )
            assert raw.status_code == 413

            boundary = "tones-cfg-boundary"
            multipart_prefix_and_file = (
                (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="file"; filename="synthetic.cfg"\r\n'
                    "Content-Type: text/plain\r\n\r\n"
                ).encode()
                + valid_config
                + f"\r\n--{boundary}--\r\n".encode()
            )
            uploaded = await client.post(
                "/api/import/tones-cfg?apply=true&mode=replace",
                content=_three_chunks(
                    multipart_prefix_and_file,
                    b"\n",
                    b"x" * (MAX_TONES_CFG_IMPORT_BYTES + 64 * 1024 + 1),
                ),
                headers={
                    "Authorization": f"Bearer {token}",
                    "content-type": f"multipart/form-data; boundary={boundary}",
                },
            )
            assert uploaded.status_code == 413

            assert app.state.config == initial
            assert app.state.supervisor.config == initial
            assert store.load() == initial
            assert (root / "config.yaml").read_bytes() == before_yaml
            audit = await client.get("/api/audit", headers={"Authorization": f"Bearer {token}"})
            assert not [
                item for item in audit.json()["items"] if item["event_type"] == "tones_cfg_import"
            ]


@pytest.mark.asyncio
async def test_tones_cfg_guard_covers_trailing_slash_and_root_path() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        ConfigStore(root).save(AppConfig())
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with app.router.lifespan_context(app):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            payload = _oversized_synthetic_config()
            for root_path, request_path in (
                ("", "/api/import/tones-cfg/"),
                ("/prefix", "/api/import/tones-cfg/"),
            ):
                transport = httpx.ASGITransport(app=app, root_path=root_path)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        f"{request_path}?apply=true&mode=replace",
                        content=_chunks(payload),
                        headers={
                            "Authorization": f"Bearer {token}",
                            "content-type": "text/plain",
                        },
                    )
                    assert response.status_code == 413

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                unrelated = await client.post(
                    "/x/api/import/tones-cfg",
                    content=_chunks(b"x" * (MAX_TONES_CFG_IMPORT_BYTES + 1)),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "content-type": "text/plain",
                    },
                )
                assert unrelated.status_code == 404
