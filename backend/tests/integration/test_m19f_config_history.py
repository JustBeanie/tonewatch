import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from tonewatch.api.app import MAX_TONES_CFG_IMPORT_BYTES, _TonesCfgBodyLimitMiddleware, create_app
from tonewatch.config.history import ConfigHistory, HistoryError
from tonewatch.config.models import AppConfig, MqttTarget
from tonewatch.settings import Settings


def test_history_records_and_prunes_versions(tmp_path: Path) -> None:
    history = ConfigHistory(tmp_path)
    for _ in range(101):
        history.record(AppConfig(), actor="test", route="/api/config")
    versions = history.list_versions()
    assert len(versions) == 100
    assert versions[0]["id"]
    assert versions[0]["sha256"]


def test_history_files_are_owner_only_on_posix(tmp_path: Path) -> None:
    if os.name == "nt":
        return
    history = ConfigHistory(tmp_path)
    version = history.record(AppConfig(), actor="test", route="/api/config")
    assert (history.root / f"{version['id']}.yaml").stat().st_mode & 0o777 == 0o600


def test_history_masked_diff_never_contains_secret(tmp_path: Path) -> None:
    history = ConfigHistory(tmp_path)
    before = AppConfig(
        alert_targets=[MqttTarget(id="mqtt", name="MQTT", password="fixture-secret")]  # noqa: S106 -- fixture-only sentinel
    )
    first = history.record(before, actor="test", route="/api/config")
    second = history.record(AppConfig(), actor="test", route="/api/config")
    assert "fixture-secret" not in str(history.masked_content(first["id"]))
    assert "fixture-secret" not in str(history.diff(first["id"], second["id"]))


def test_history_exposes_public_raw_config(tmp_path: Path) -> None:
    history = ConfigHistory(tmp_path)
    version = history.record(AppConfig(), actor="test", route="/api/config")
    assert history.raw_config(version["id"]) == AppConfig().model_dump(mode="json")


@pytest.mark.asyncio
async def test_config_history_export_import_and_rollback() -> None:  # noqa: PLR0915 -- one end-to-end contract covers the required save/export/import/rollback sequence.
    with TemporaryDirectory() as directory:
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
            target = {
                "id": "mqtt",
                "name": "MQTT",
                "type": "mqtt",
                "password": "fixture-secret",
            }
            assert (
                await client.post("/api/alert-targets", json=target, headers=headers)
            ).status_code == 201
            versions = (await client.get("/api/admin/config/versions", headers=headers)).json()
            assert len(versions) == 2  # startup baseline plus the successful target save
            version_id = versions[0]["id"]
            assert (
                await client.get("/api/admin/config/versions/missing", headers=headers)
            ).status_code == 404
            assert (
                await client.get("/api/admin/config/versions/missing/diff", headers=headers)
            ).status_code == 404
            assert (
                await client.get(
                    f"/api/admin/config/versions/{version_id}/diff?against={version_id}",
                    headers=headers,
                )
            ).status_code == 200
            tone = {
                "id": "fire",
                "name": "Fire",
                "sequence": [{"freq_hz": 1000, "min_s": 1}],
            }
            assert (
                await client.post("/api/tonesets", json=tone, headers=headers)
            ).status_code == 201
            assert (
                len((await client.get("/api/admin/config/versions", headers=headers)).json()) == 3
            )
            imported = await client.post(
                "/api/import/tones-cfg?apply=true",
                content=b"[Imported]\nlongtone=1200\nlongtonelength=1\n",
                headers=headers,
            )
            assert imported.status_code == 200
            assert (
                len((await client.get("/api/admin/config/versions", headers=headers)).json()) == 4
            )
            serialized = (
                await client.get(f"/api/admin/config/versions/{version_id}", headers=headers)
            ).text
            assert "fixture-secret" not in serialized
            exported = await client.get("/api/admin/config/export?format=json", headers=headers)
            assert exported.status_code == 200
            assert "fixture-secret" not in exported.text
            assert exported.headers["cache-control"] == "no-store"
            assert "attachment" in exported.headers["content-disposition"]
            assert (
                await client.get("/api/admin/config/export?include_secrets=true", headers=headers)
            ).status_code == 422
            assert (
                await client.get(
                    "/api/admin/config/export?format=json&include_secrets=true&confirm=include-secrets",
                    headers=headers,
                )
            ).status_code == 422

            config_path = root / "config.yaml"
            before = config_path.read_bytes()
            preview = await client.post(
                "/api/admin/config/import/preview",
                content=b'{"alert_targets":[{"id":"mqtt","name":"Changed","type":"mqtt","password":"[REDACTED]"}]}',
                headers={**headers, "content-type": "application/json"},
            )
            assert preview.status_code == 200
            assert not preview.json()["applied"]
            assert config_path.read_bytes() == before
            assert (
                await client.post(
                    "/api/admin/config/import/preview",
                    content=b"not: [valid",
                    headers={**headers, "content-type": "application/yaml"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/admin/config/import/preview",
                    content=b"[]",
                    headers={**headers, "content-type": "application/json"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/admin/config/import/preview",
                    content=b'{"alert_targets":[{"id":"new","name":"New","type":"mqtt","password":"[REDACTED]"}]}',
                    headers={**headers, "content-type": "application/json"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/admin/config/import/preview",
                    content=b"x" * (256 * 1024 + 1),
                    headers={**headers, "content-type": "application/yaml"},
                )
            ).status_code == 413
            etag = (await client.get("/api/config", headers=headers)).headers["etag"]
            stale = await client.post(
                "/api/admin/config/import/apply",
                content=b'{"alert_targets":[]}',
                headers={**headers, "content-type": "application/json", "if-match": '"stale"'},
            )
            assert stale.status_code == 412
            missing = await client.post(
                "/api/admin/config/import/apply",
                content=b'{"alert_targets":[]}',
                headers={**headers, "content-type": "application/json"},
            )
            assert missing.status_code == 428
            applied = await client.post(
                "/api/admin/config/import/apply",
                content=b'{"alert_targets":[{"id":"mqtt","name":"Changed","type":"mqtt","password":"[REDACTED]"}]}',
                headers={**headers, "content-type": "application/json", "if-match": etag},
            )
            assert applied.status_code == 200
            assert (await client.get("/api/alert-targets/mqtt", headers=headers)).json()[
                "password"
            ] == "[REDACTED]"  # noqa: S105 -- assert the public redaction sentinel

            current_etag = (await client.get("/api/config", headers=headers)).headers["etag"]
            rolled = await client.post(
                f"/api/admin/config/versions/{version_id}/rollback",
                headers={**headers, "if-match": current_etag},
            )
            assert rolled.status_code == 200
            assert (await client.get("/api/alert-targets/mqtt", headers=headers)).json()[
                "name"
            ] == "MQTT"
            assert (
                await client.post(
                    f"/api/admin/config/versions/{version_id}/rollback", headers=headers
                )
            ).status_code == 428

            attack = await client.post(
                "/api/admin/config/import/preview",
                content=b"!!python/object:__main__.Bad {}",
                headers={**headers, "content-type": "application/yaml"},
            )
            assert attack.status_code == 422
            assert (
                await client.post("/api/admin/config/versions/missing/rollback", headers=headers)
            ).status_code == 428


@pytest.mark.asyncio
async def test_config_history_auth_matrix() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            endpoints = [
                ("GET", "/api/admin/config/versions"),
                ("GET", "/api/admin/config/export"),
                ("POST", "/api/admin/config/import/preview"),
                ("POST", "/api/admin/config/import/apply"),
                ("POST", "/api/admin/config/versions/missing/rollback"),
            ]
            for method, path in endpoints:
                response = await client.request(method, path, content=b"{}")
                assert response.status_code == 401, (method, path, response.text)


@pytest.mark.asyncio
async def test_secret_export_post_requires_csrf_and_bearer_is_audited() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(
            Settings(
                data_dir=root,
                ui_password="password",  # noqa: S106 -- fixture-only session password
                zeroconf_enabled=False,
            )
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            login = await client.post("/api/auth/login", json={"password": "password"})
            assert login.status_code == 200
            body = {"format": "json", "include_secrets": True, "confirm": "include-secrets"}
            no_csrf = await client.post("/api/admin/config/export", json=body)
            assert no_csrf.status_code == 403
            token = (root / "api_token").read_text(encoding="ascii").strip()
            exported = await client.post(
                "/api/admin/config/export",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert exported.status_code == 200
            audit = await client.get("/api/audit", headers={"Authorization": f"Bearer {token}"})
            assert any(
                item["event_type"] == "config_export_secrets" for item in audit.json()["items"]
            )

    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, addon_mode=True, zeroconf_enabled=False))
        transport = httpx.ASGITransport(app=app, client=("172.30.32.2", 1234))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            ingress = await client.post(
                "/api/admin/config/export",
                json={"format": "json", "include_secrets": True, "confirm": "include-secrets"},
                headers={"x-ingress-path": "/x"},
            )
            assert ingress.status_code == 403


@pytest.mark.asyncio
async def test_history_failure_does_not_fail_saved_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with TemporaryDirectory() as directory:
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

            def fail(*_args: object, **_kwargs: object) -> None:
                raise HistoryError("history disk unavailable")  # noqa: TRY003 -- fixture failure reason

            monkeypatch.setattr(ConfigHistory, "record", fail)
            response = await client.put(
                "/api/config",
                json={
                    "tone_sets": [
                        {
                            "id": "history-test",
                            "name": "History test",
                            "sequence": [{"freq_hz": 1000, "min_s": 1}],
                        }
                    ]
                },
                headers=headers,
            )
            assert response.status_code == 200
            assert app.state.config.tone_sets[0].id == "history-test"
            assert "history disk unavailable" in capsys.readouterr().err
            audit = await client.get("/api/audit", headers=headers)
            assert audit.json()["items"][0]["details"]["history_recorded"] is False


@pytest.mark.asyncio
async def test_startup_creates_one_baseline_version_and_restart_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = Settings(data_dir=root, zeroconf_enabled=False)
        for _ in range(2):
            app = create_app(settings)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client,
            ):
                token = (root / "api_token").read_text(encoding="ascii").strip()
                versions = (
                    await client.get(
                        "/api/admin/config/versions",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                ).json()
                assert len(versions) == 1
                assert versions[0]["actor"] == "system"
                assert versions[0]["route"] == "startup"


@pytest.mark.asyncio
async def test_config_import_limit_streams_without_content_length() -> None:
    called = False

    async def downstream(
        _scope: object,
        downstream_receive: Callable[[], Awaitable[dict[str, object]]],
        _send: object,
    ) -> None:
        nonlocal called
        called = True
        while True:
            message = await downstream_receive()
            if message["type"] == "http.disconnect":
                return

    messages = iter(
        [
            {"type": "http.request", "body": b"x" * MAX_TONES_CFG_IMPORT_BYTES, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    middleware = _TonesCfgBodyLimitMiddleware(downstream, MAX_TONES_CFG_IMPORT_BYTES)
    await middleware(
        {"type": "http", "path": "/api/admin/config/import/apply", "root_path": "", "headers": []},
        receive,
        send,
    )
    assert sent[0]["status"] == 413
