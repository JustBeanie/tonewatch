"""M19g support bundle and log viewer contracts."""

import hashlib
import inspect
import io
import json
import logging
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args
from uuid import uuid4

import httpx
import pytest
import structlog
from pydantic import AnyUrl
from sqlalchemy import select

from tonewatch.api.app import create_app
from tonewatch.api.audit import is_secret_key
from tonewatch.config.models import (
    AppConfig,
    FileSource,
    MapConfig,
    MqttTarget,
    StreamSource,
    WebhookTarget,
)
from tonewatch.logging import LogRing, LogRingHandler, SecretHolder, configure_logging
from tonewatch.settings import Settings
from tonewatch.storage.models import AuditEvent, CadIncident, Call, Recording


def test_m19g_ring_redacts_rotated_secrets_and_is_bounded() -> None:
    ring = LogRing(max_records=32, max_record_bytes=4096)
    holder = SecretHolder("old-api-token")
    configure_logging("INFO", api_token=holder.current, token_holder=holder, ring=ring)
    for handler in logging.getLogger().handlers:
        if hasattr(handler, "setStream"):
            handler.setStream(io.StringIO())
    logger = structlog.get_logger("m19g.test")
    logger.info(
        "fixture",
        old="old-api-token",
        new="new-api-token",
        password="password-fixture",  # noqa: S106 -- synthetic fixture credential.
        url="https://example.test/hook?t=query-secret",
        psk="AQIDBAUGBwgJCgsMDQ4PEA==",
    )
    holder.current = "new-api-token"
    logger.info("rotated", message="new-api-token")
    for index in range(5000):
        logger.info("many", index=index)
    logger.info("large", message="x" * 1_000_000)
    rendered = json.dumps(ring.records())
    assert "old-api-token" not in rendered
    assert "new-api-token" not in rendered
    assert "password-fixture" not in rendered
    assert "query-secret" not in rendered
    assert "AQIDBAUGBwgJCgsMDQ4PEA==" not in rendered
    assert len(ring.records()) == 32
    assert any(item.get("truncated") for item in ring.records())


def test_m19g_logging_has_no_production_test_seam() -> None:
    source = inspect.getsource(LogRingHandler)
    assert "def setStream" not in source


@pytest.mark.asyncio
async def test_m19g_log_api_filters_tails_and_requires_auth() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, ui_password="ui-secret", zeroconf_enabled=False))  # noqa: S106 -- synthetic fixture credential.
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            logger = structlog.get_logger("m19g.api")
            logger.info("visible")
            logger.error("error-visible")
            assert (await client.get("/api/admin/logs")).status_code == 401
            response = await client.get(
                "/api/admin/logs",
                headers={"Authorization": f"Bearer {token}"},
                params={"level": "ERROR"},
            )
            assert response.status_code == 200
            assert all(item["level"] in {"error", "critical"} for item in response.json()["items"])
            items = response.json()["items"]
            assert items
            tail = await client.get(
                "/api/admin/logs",
                headers={"Authorization": f"Bearer {token}"},
                params={"since_seq": items[-1]["seq"]},
            )
            assert all(item["seq"] > items[-1]["seq"] for item in tail.json()["items"])
            assert (
                await client.get(
                    "/api/admin/logs?limit=501", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 422
            assert (
                await client.get(
                    "/api/admin/logs?level=NOT_A_LEVEL",
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).status_code == 422


def _declared_secret_fields(model: type[object]) -> set[str]:
    """Walk nested Pydantic declarations so fixture coverage follows the schema."""
    result: set[str] = set()
    fields = getattr(model, "model_fields", {})

    def visit(annotation: object) -> None:
        if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
            result.update(_declared_secret_fields(annotation))
            return
        for nested in get_args(annotation):
            visit(nested)

    for name, field in fields.items():
        if is_secret_key(name):
            result.add(name)
        visit(field.annotation)
    return result


@pytest.mark.asyncio
async def test_m19g_bundle_scrubs_health_urls_paths_and_model_driven_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".docker").write_text("fixture marker", encoding="utf-8")
        home = Path.home()
        app = create_app(Settings(data_dir=root, zeroconf_enabled=False))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            config = AppConfig(
                sources=[
                    FileSource(
                        id="file-sentinel",
                        name="File",
                        path=str(root / "recordings" / "private.wav"),
                    ),
                    StreamSource(
                        id="stream-sentinel",
                        name="Stream",
                        url=AnyUrl(
                            "https://stream-user:stream-pass@stream-host.invalid/live?t=stream-query"
                        ),
                    ),
                ],
                map=MapConfig().model_copy(
                    update={"tile_url": "https://tile-host.invalid/{z}/{x}/{y}?key=tile-query"}
                ),
                alert_targets=[
                    WebhookTarget(
                        id="hook-sentinel",
                        name="Hook",
                        url=AnyUrl(
                            "https://web-user:web-pass@web-host.invalid/hook?token=web-query"
                        ),
                        secret="webhook-secret-sentinel",  # noqa: S106 -- synthetic fixture credential.
                    ),
                    MqttTarget(
                        id="mqtt-sentinel",
                        name="MQTT",
                        host="mqtt-host-sentinel.invalid",
                        username="mqtt-user-sentinel",
                        password="mqtt-password-sentinel",  # noqa: S106 -- synthetic fixture credential.
                    ),
                ],
            )
            app.state.config = config
            declared_secrets = _declared_secret_fields(AppConfig)
            assert {"password", "secret"} <= declared_secrets
            call_id = uuid4()
            async with app.state.session_factory() as session:
                session.add(
                    Call(
                        id=call_id,
                        source_id="file-sentinel",
                        started_at=datetime.now(UTC),
                    )
                )
                session.add(
                    Recording(
                        call_id=call_id,
                        format="wav",
                        path=str(root / "recordings" / "private-recording.wav"),
                        duration_s=2.0,
                        size_bytes=12,
                    )
                )
                session.add(
                    CadIncident(
                        feed_id="cad-sentinel",
                        incident_id="incident-sentinel",
                        agency_name="Agency",
                        agency_key="agency",
                        type_raw="Alarm",
                        type_key="alarm",
                        address_clean="123 Secret Street",
                        cross_streets=["Secret Street", "Hidden Avenue"],
                        received_at=datetime.now(UTC),
                        status="active",
                        first_seen_at=datetime.now(UTC),
                        last_seen_at=datetime.now(UTC),
                    )
                )
                await session.commit()

            async def fake_health(_request: object) -> dict[str, object]:
                return {
                    "sources": [
                        {
                            "last_error": (
                                "stream https://health-user:health-pass@health-host.invalid/x?"
                                "q=health-query at " + os.fspath(home / "health-private")
                            )
                        }
                    ],
                    "outputs": [
                        {
                            "last_error": (
                                "mqtt-host-sentinel.invalid " + os.fspath(root / "health-private")
                            )
                        }
                    ],
                }

            monkeypatch.setattr("tonewatch.api.routes.support.health", fake_health)
            structlog.get_logger("m19g.fixture").error(
                "credentialed https://log-user:log-pass@log-host.invalid/x?token=log-query "
                + os.fspath(root / "log-private")
            )
            token = (root / "api_token").read_text(encoding="ascii").strip()
            response = await client.post(
                "/api/admin/support-bundle",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                payload = b"".join(archive.read(name) for name in archive.namelist())
                environment = json.loads(archive.read("environment.json"))
                assert environment["mode"]["docker"] is False
            text = payload.decode("utf-8", "replace")
            for sentinel in (
                "stream-user",
                "stream-pass",
                "stream-host.invalid",
                "stream-query",
                "tile-host.invalid",
                "tile-query",
                "web-user",
                "web-pass",
                "web-host.invalid",
                "web-query",
                "mqtt-host-sentinel.invalid",
                "mqtt-user-sentinel",
                "mqtt-password-sentinel",
                "health-user",
                "health-pass",
                "health-host.invalid",
                "health-query",
                "log-user",
                "log-pass",
                "log-host.invalid",
                "log-query",
            ):
                assert sentinel not in text
            assert str(root) not in text
            assert str(home) not in text
            assert str(root).replace("\\", "/") not in text
            assert str(home).replace("\\", "/") not in text
            assert "123 Secret Street" not in text
            assert "private-recording.wav" not in text


@pytest.mark.asyncio
async def test_m19g_bundle_is_secret_free_audited_and_bounded() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root, ui_password="ui-secret", zeroconf_enabled=False))  # noqa: S106 -- synthetic fixture credential.
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            app.state.config = AppConfig(
                alert_targets=[
                    WebhookTarget(
                        id="hook",
                        name="Hook",
                        url=AnyUrl("https://user:secret-webhook@example.test/x"),
                    ),
                    MqttTarget(
                        id="mqtt",
                        name="MQTT",
                        host="mqtt-secret.example",
                        password="mqtt-password",  # noqa: S106 -- synthetic fixture credential.
                    ),
                ]
            )
            token = (root / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.post("/api/admin/support-bundle", headers=headers)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = set(archive.namelist())
                assert {
                    "manifest.json",
                    "config.redacted.yaml",
                    "health.json",
                    "logs.jsonl",
                    "detections.json",
                    "environment.json",
                } <= names
                manifest = json.loads(archive.read("manifest.json"))
                for item in manifest["files"]:
                    assert hashlib.sha256(archive.read(item["name"])).hexdigest() == item["sha256"]
                payload = b"".join(archive.read(name) for name in names)
                for secret in ("secret-webhook", "mqtt-password", "mqtt-secret.example"):
                    assert secret.encode() not in payload
            assert (
                await client.post("/api/admin/support-bundle", headers=headers)
            ).status_code == 429
            async with app.state.session_factory() as session:
                audited = list(
                    (
                        await session.execute(
                            select(AuditEvent).where(
                                AuditEvent.event_type == "support_bundle_created"
                            )
                        )
                    ).scalars()
                )
            assert len(audited) == 1
            login = await client.post("/api/auth/login", json={"password": "ui-secret"})
            assert login.status_code == 200
            assert (await client.post("/api/admin/support-bundle")).status_code == 403
