"""M19a admin API contracts (G--I)."""

import asyncio
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import AnyUrl
from sqlalchemy import select

from tonewatch.alerts.meshtastic import MeshtasticResult
from tonewatch.alerts.webhook import WebhookResult
from tonewatch.api.app import create_app
from tonewatch.api.routes.admin import _cursor
from tonewatch.config.models import (
    AppConfig,
    FileSource,
    MeshtasticTarget,
    MqttTarget,
    WebhookTarget,
)
from tonewatch.settings import Settings
from tonewatch.storage.models import AlertAttempt, AuditEvent, Call


@pytest.mark.asyncio
async def test_m19a_g_health_auth_schema_nulls_and_secret_free() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(
            Settings.model_validate(
                {"data_dir": root, "ui_password": "https://user:pw@example.test"}
            )
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await client.get("/api/admin/health")).status_code == 401
            token = (root / "api_token").read_text(encoding="ascii").strip()
            body = (
                await client.get("/api/admin/health", headers={"Authorization": f"Bearer {token}"})
            ).json()
            assert set(body) == {
                "generated_at",
                "sources",
                "service",
                "storage",
                "outputs",
                "build",
            }
            assert set(body["storage"]) == {
                "recordings_bytes",
                "free_bytes",
                "db_bytes",
                "db_wal_bytes",
                "retention_forecast",
            }
            assert body["build"]["version"]
            assert "https://user:pw@example.test" not in str(body)


@pytest.mark.asyncio
async def test_m19a_h_delivery_filters_cursor_limit_and_auth() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            call_id = uuid4()
            async with app.state.session_factory() as session:
                session.add(Call(id=call_id, source_id="radio", started_at=datetime.now(UTC)))
                for index in range(3):
                    session.add(
                        AlertAttempt(
                            call_id=call_id,
                            target_id="target",
                            phase="pre_alert" if index < 2 else "closed",
                            attempt_no=index + 1,
                            ok=index == 2,
                            created_at=datetime.now(UTC) + timedelta(seconds=index),
                        )
                    )
                await session.commit()
            assert (
                await client.get(
                    "/api/admin/alert-attempts",
                    headers=headers,
                    params={"call_id": str(call_id)},
                )
            ).json()["items"]
            filters = (
                ("target_id", "target"),
                ("phase", "closed"),
                ("ok", "true"),
                ("since", "2025-01-01T00:00:00Z"),
                ("until", "2030-01-01T00:00:00Z"),
            )
            for key, value in filters:
                assert (
                    await client.get(
                        "/api/admin/alert-attempts", headers=headers, params={key: value}
                    )
                ).status_code == 200
            first = await client.get(
                "/api/admin/alert-attempts", headers=headers, params={"limit": 2}
            )
            second = await client.get(
                "/api/admin/alert-attempts",
                headers=headers,
                params={"limit": 2, "cursor": first.json()["next_cursor"]},
            )
            assert {item["id"] for item in first.json()["items"]}.isdisjoint(
                {item["id"] for item in second.json()["items"]}
            )
            assert (
                await client.get(
                    "/api/admin/alert-attempts", headers=headers, params={"limit": 201}
                )
            ).status_code == 422
            assert (await client.get("/api/admin/alert-attempts")).status_code == 401


@pytest.mark.asyncio
async def test_m19a_i_retry_unknown_is_authenticated_and_csrf_protected() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings.model_validate({"data_dir": root, "ui_password": "secret"}))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await client.post("/api/admin/alert-attempts/999/retry")).status_code == 401
            login = await client.post("/api/auth/login", json={"password": "secret"})
            assert login.status_code == 200
            assert (await client.post("/api/admin/alert-attempts/999/retry")).status_code == 403
            csrf = login.json()["csrf_token"]
            assert (
                await client.post(
                    "/api/admin/alert-attempts/999/retry",
                    headers={"X-CSRF-Token": csrf},
                )
            ).status_code == 404


@pytest.mark.asyncio
async def test_m19a_i_retry_full_matrix_and_delivery_audit(  # noqa: PLR0915 -- one test proves the required retry state matrix atomically.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            headers = {"Authorization": f"Bearer {token}"}
            target = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test"))
            config = AppConfig(alert_targets=[target])
            alerts = app.state.supervisor.alerts
            alerts.config = config
            calls: list[dict[str, object]] = []

            async def send_ok(
                _target: object, payload: dict[str, object], **_kwargs: object
            ) -> WebhookResult:
                calls.append(payload)
                return WebhookResult(True, status_code=204)

            monkeypatch.setattr(alerts, "_send", send_ok)
            call_id = uuid4()
            missing_call_id = uuid4()
            gone_call_id = uuid4()
            async with app.state.session_factory() as session:
                session.add_all(
                    [
                        Call(id=call_id, source_id="radio", started_at=datetime.now(UTC)),
                        Call(id=gone_call_id, source_id="radio", started_at=datetime.now(UTC)),
                    ]
                )
                failed = AlertAttempt(
                    call_id=call_id,
                    target_id="hook",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    error="old failure",
                    created_at=datetime.now(UTC),
                )
                succeeded = AlertAttempt(
                    call_id=call_id,
                    target_id="hook",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=True,
                    created_at=datetime.now(UTC),
                )
                missing_call = AlertAttempt(
                    call_id=missing_call_id,
                    target_id="hook",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    created_at=datetime.now(UTC),
                )
                gone_target = AlertAttempt(
                    call_id=gone_call_id,
                    target_id="gone",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    created_at=datetime.now(UTC),
                )
                session.add_all([failed, succeeded, missing_call, gone_target])
                await session.commit()
                failed_id, succeeded_id, missing_id, gone_id = (
                    failed.id,
                    succeeded.id,
                    missing_call.id,
                    gone_target.id,
                )

            response = await client.post(
                f"/api/admin/alert-attempts/{failed_id}/retry", headers=headers
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert calls == [
                {
                    "call_id": str(call_id),
                    "phase": "pre_alert",
                    "retry": True,
                    "source_id": "radio",
                    "test": False,
                }
            ]
            async with app.state.session_factory() as session:
                rows = list(
                    (
                        await session.execute(
                            select(AlertAttempt).where(AlertAttempt.call_id == call_id)
                        )
                    ).scalars()
                )
                audit = list(
                    (
                        await session.execute(
                            select(AuditEvent).where(
                                AuditEvent.event_type == "alert_attempt_retried"
                            )
                        )
                    ).scalars()
                )
            assert sum(row.retry for row in rows) == 1
            assert len(audit) == 1
            assert audit[0].details == {"attempt_id": failed_id, "target_id": "hook", "ok": True}
            assert (
                await client.post(
                    f"/api/admin/alert-attempts/{succeeded_id}/retry", headers=headers
                )
            ).status_code == 409
            assert (
                await client.post(f"/api/admin/alert-attempts/{missing_id}/retry", headers=headers)
            ).status_code == 409
            assert (
                await client.post(f"/api/admin/alert-attempts/{gone_id}/retry", headers=headers)
            ).status_code == 409
            assert (
                await client.post("/api/admin/alert-attempts/999999/retry", headers=headers)
            ).status_code == 404

            entered = asyncio.Event()
            release = asyncio.Event()

            async def send_slow(
                _target: object, _payload: dict[str, object], **_kwargs: object
            ) -> WebhookResult:
                entered.set()
                await release.wait()
                return WebhookResult(True)

            monkeypatch.setattr(alerts, "_send", send_slow)
            async with app.state.session_factory() as session:
                concurrent = AlertAttempt(
                    call_id=call_id,
                    target_id="hook",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    created_at=datetime.now(UTC),
                )
                session.add(concurrent)
                await session.commit()
                concurrent_id = concurrent.id
            first = asyncio.create_task(
                client.post(f"/api/admin/alert-attempts/{concurrent_id}/retry", headers=headers)
            )
            await entered.wait()
            second = await client.post(
                f"/api/admin/alert-attempts/{concurrent_id}/retry", headers=headers
            )
            assert second.status_code == 429
            release.set()
            assert (await first).status_code == 200

            mesh = MeshtasticTarget(
                id="mesh",
                name="Mesh",
                host="localhost",
                gateway_node_id="!12345678",
                acknowledge_public_channel=True,
                timeout_s=0.01,
            )
            alerts.config = AppConfig(alert_targets=[mesh])
            async with app.state.session_factory() as session:
                timeout_attempt = AlertAttempt(
                    call_id=call_id,
                    target_id="mesh",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    created_at=datetime.now(UTC),
                )
                limited_attempt = AlertAttempt(
                    call_id=call_id,
                    target_id="mesh",
                    phase="pre_alert",
                    attempt_no=1,
                    ok=False,
                    created_at=datetime.now(UTC),
                )
                session.add_all([timeout_attempt, limited_attempt])
                await session.commit()

            async def send_timeout(
                _target: object, _payload: dict[str, object], **_kwargs: object
            ) -> WebhookResult:
                await asyncio.sleep(1)
                return WebhookResult(True)

            monkeypatch.setattr(alerts, "_send", send_timeout)
            timed = await client.post(
                f"/api/admin/alert-attempts/{timeout_attempt.id}/retry", headers=headers
            )
            assert timed.status_code == 200
            assert timed.json() == {"ok": False, "error": "target timeout", "target_id": "mesh"}

            async def send_limited(
                _target: object, _payload: dict[str, object], **_kwargs: object
            ) -> MeshtasticResult:
                return MeshtasticResult(False, "rate_limited")

            monkeypatch.setattr(alerts, "_send", send_limited)
            limited = await client.post(
                f"/api/admin/alert-attempts/{limited_attempt.id}/retry", headers=headers
            )
            assert limited.status_code == 200
            assert limited.json()["error"] == "rate_limited"
            async with app.state.session_factory() as session:
                persisted = await session.get(AlertAttempt, limited_attempt.id)
                retry_rows = list(
                    (
                        await session.execute(
                            select(AlertAttempt).where(
                                AlertAttempt.call_id == call_id,
                                AlertAttempt.target_id == "mesh",
                                AlertAttempt.retry.is_(True),
                            )
                        )
                    ).scalars()
                )
            assert persisted is not None and persisted.retry is False
            assert len(retry_rows) >= 2


@pytest.mark.asyncio
async def test_m19a_g_health_target_output_and_bad_cursor() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            app.state.config = AppConfig(alert_targets=[MqttTarget(id="mqtt", name="MQTT")])
            response = await client.get(
                "/api/admin/health", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["outputs"][0]["connection"] is None
            with pytest.raises(HTTPException) as error:
                _cursor("not-a-cursor")
            assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_m19a_g_source_null_fields_and_i_audit_success() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(Settings(data_dir=root))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            token = (root / "api_token").read_text(encoding="ascii").strip()
            app.state.config = AppConfig(
                sources=[FileSource(id="radio", name="Radio", path="missing.wav")]
            )
            body = (
                await client.get("/api/admin/health", headers={"Authorization": f"Bearer {token}"})
            ).json()
            assert body["sources"][0]["realtime_factor"] is None
            assert body["sources"][0]["squelch_open"] is None

            async def stop() -> None:
                return None

            app.state.supervisor = SimpleNamespace(
                alerts=SimpleNamespace(retry_attempt=_retry_success), stop=stop
            )
            response = await client.post(
                "/api/admin/alert-attempts/1/retry",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True


async def _retry_success(_attempt_id: int) -> tuple[int, dict[str, object]]:
    return 200, {"ok": True, "error": None, "target_id": "target"}


def test_m19a_k_s4_security_is_untouched() -> None:
    git = shutil.which("git")
    assert git is not None
    result = subprocess.run(  # noqa: S603 -- executable is resolved from PATH and arguments are constants.
        [git, "diff", "origin/main", "--", "backend/tests/unit/test_s4_security.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
