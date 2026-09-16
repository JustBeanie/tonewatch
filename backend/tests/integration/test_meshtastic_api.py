"""M18a Meshtastic API, audit, and dispatcher integration coverage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from pydantic import AnyUrl
from sqlalchemy import select

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.meshtastic import MeshtasticResult, MeshtasticSender, render_message
from tonewatch.api.app import create_app
from tonewatch.config.models import (
    AppConfig,
    MeshtasticTarget,
    MqttTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.config.store import ConfigStore
from tonewatch.events import EventBus, ToneDetected
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import AlertAttempt, AuditEvent, Call

if TYPE_CHECKING:
    from pathlib import Path


class FakeAlerts:
    async def test_target(self, _target_id: str) -> dict[str, object]:
        return {"ok": True, "error": None}


class FakeSupervisor:
    def __init__(self) -> None:
        self.alerts: Any = FakeAlerts()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def reload(self, _config: AppConfig) -> None:
        return None


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, zeroconf_enabled=False)


def mesh_target() -> MeshtasticTarget:
    return MeshtasticTarget(
        id="mesh",
        name="Mesh",
        host="127.0.0.1",
        gateway_node_id="!9abc1234",
        channel_index=1,
        password="invented-mesh-password",  # noqa: S106 -- invented test credential.
        timeout_s=0.05,
    )


@pytest.mark.asyncio
async def test_meshtastic_password_is_masked_in_api_and_config_audits(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    supervisor = FakeSupervisor()
    app = create_app(_settings(tmp_path), supervisor=supervisor, session_factory=sessions)
    token = app.state.auth.token
    headers = {"Authorization": f"Bearer {token}"}
    payload = mesh_target().model_dump(mode="json")
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        created = await client.post("/api/alert-targets", headers=headers, json=payload)
        assert created.status_code == 201
        listed = await client.get("/api/alert-targets", headers=headers)
        fetched = await client.get("/api/alert-targets/mesh", headers=headers)
        assert listed.json()[0]["password"] == "[REDACTED]"  # noqa: S105 -- redaction assertion.
        assert fetched.json()["password"] == "[REDACTED]"  # noqa: S105 -- redaction assertion.
        updated = dict(fetched.json(), name="Renamed Mesh")
        response = await client.put("/api/alert-targets/mesh", headers=headers, json=updated)
        assert response.status_code == 200
    expected_password = "invented-mesh-password"  # noqa: S105 -- invented test credential.
    assert app.state.config.alert_targets[0].password == expected_password
    async with sessions() as session:
        audits = list((await session.scalars(select(AuditEvent))).all())
    assert audits
    assert "invented-mesh-password" not in str(audits)
    await engine.dispose()


@pytest.mark.asyncio
async def test_meshtastic_preview_is_utf8_safe_and_does_not_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    payload = mesh_target().model_dump(mode="json") | {
        "template": "{agency_short} é🙂 {toneset}",
        "max_bytes": 14,
    }

    def fail_constructor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr("tonewatch.alerts.meshtastic.aiomqtt.Client", fail_constructor)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/alert-targets/meshtastic/preview",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "TEST AFD é…"
    assert body["bytes"] == len(body["text"].encode())
    assert body["bytes"] <= body["max_bytes"]
    assert body["truncated"] is True
    assert "password" not in body and "invented-mesh-password" not in str(body)


@pytest.mark.asyncio
async def test_meshtastic_preview_flags_truncation_at_default_max_bytes(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    payload = mesh_target().model_dump(mode="json") | {"template": "é🙂" * 100}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/alert-targets/meshtastic/preview",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    body = response.json()
    assert body["truncated"] is True
    assert body["bytes"] <= 200
    body["text"].encode("utf-8")


@pytest.mark.asyncio
async def test_meshtastic_preview_exact_max_bytes_is_not_truncated(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    payload = mesh_target().model_dump(mode="json") | {"template": "x" * 195}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/alert-targets/meshtastic/preview",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    body = response.json()
    assert body["bytes"] == 200
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_meshtastic_preview_auth_and_validation(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    valid = mesh_target().model_dump(mode="json")
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (
            await client.post("/api/alert-targets/meshtastic/preview", json=valid)
        ).status_code == 401
        invalid = dict(valid, gateway_node_id="bad", channel_index=8, mqtt_target_id="mqtt")
        assert (
            await client.post(
                "/api/alert-targets/meshtastic/preview",
                headers={"Authorization": f"Bearer {token}"},
                json=invalid,
            )
        ).status_code == 422


@pytest.mark.asyncio
async def test_alert_target_secret_round_trip_for_all_target_types(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    targets = [
        MqttTarget(id="mqtt", name="MQTT", password="mqtt-secret"),  # noqa: S106 -- invented test credential.
        WebhookTarget(
            id="hook",
            name="Hook",
            url=AnyUrl("https://example.com"),
            secret="hook-secret",  # noqa: S106 -- invented test credential.
        ),
        mesh_target(),
    ]
    target_ids = ["mqtt", "hook", "mesh"]
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        for target, target_id in zip(targets, target_ids, strict=True):
            created = await client.post(
                "/api/alert-targets", headers=headers, json=target.model_dump(mode="json")
            )
            assert created.status_code == 201
            fetched = await client.get(f"/api/alert-targets/{target_id}", headers=headers)
            assert fetched.status_code == 200
            assert "[REDACTED]" in fetched.text
            unchanged = await client.put(
                f"/api/alert-targets/{target_id}", headers=headers, json=fetched.json()
            )
            assert unchanged.status_code == 200
        stored_items = cast("list[Any]", app.state.config.alert_targets)
        stored = {item.id: item for item in stored_items}
        expected_mqtt = "mqtt-secret"
        expected_hook = "hook-secret"
        assert stored["mqtt"].password == expected_mqtt
        assert stored["hook"].secret == expected_hook
        assert stored["mesh"].password == "invented-mesh-password"  # noqa: S105 -- invented test credential.
        for target_id in target_ids:
            body = (await client.get(f"/api/alert-targets/{target_id}", headers=headers)).json()
            for key in ("password", "secret"):
                if key in body:
                    body[key] = None
            cleared = await client.put(
                f"/api/alert-targets/{target_id}", headers=headers, json=body
            )
            assert cleared.status_code == 200
    stored_items = cast("list[Any]", app.state.config.alert_targets)
    stored = {item.id: item for item in stored_items}
    assert stored["mqtt"].password is None
    assert stored["hook"].secret == ""
    assert stored["mesh"].password is None


@pytest.mark.asyncio
async def test_redacted_placeholder_without_stored_secret_is_rejected(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), supervisor=FakeSupervisor())
    token = app.state.auth.token
    headers = {"Authorization": f"Bearer {token}"}
    target = MqttTarget(id="mqtt-empty", name="MQTT", password=None)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (
            await client.post(
                "/api/alert-targets", headers=headers, json=target.model_dump(mode="json")
            )
        ).status_code == 201
        body = (await client.get("/api/alert-targets/mqtt-empty", headers=headers)).json()
        body["password"] = "[REDACTED]"  # noqa: S105 -- deliberate redaction placeholder.
        response = await client.put("/api/alert-targets/mqtt-empty", headers=headers, json=body)
    assert response.status_code == 422
    assert app.state.config.alert_targets[0].password is None


@pytest.mark.asyncio
async def test_alert_target_route_uses_real_dispatcher_without_attempt_rows(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'dispatcher.sqlite'}")
    await create_database_schema(engine)
    item = mesh_target()
    ConfigStore(tmp_path).save(AppConfig(alert_targets=[item]))
    supervisor = FakeSupervisor()
    app = create_app(_settings(tmp_path), supervisor=supervisor, session_factory=sessions)
    dispatcher = AlertDispatcher(
        AppConfig(alert_targets=[item]), EventBus(), sessions, settings=_settings(tmp_path)
    )
    sent = 0
    published: list[dict[str, object]] = []

    class Sender:
        async def send(self, _payload: dict[str, object]) -> Any:
            nonlocal sent
            sent += 1
            published.append(_payload)
            return type("Result", (), {"ok": True, "error": None})()

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    supervisor.alerts = dispatcher
    token = app.state.auth.token
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/alert-targets/mesh/test",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.json() == {"ok": True, "error": None}
    assert sent == 1
    assert published[0]["test"] is True
    assert render_message(item, published[0]).startswith("TEST ")
    async with sessions() as session:
        attempts = list((await session.scalars(select(AlertAttempt))).all())
        audits = list((await session.scalars(select(AuditEvent))).all())
    assert attempts == []
    target_tests = [item for item in audits if item.event_type == "alert_target_test"]
    assert len(target_tests) == 1
    assert target_tests[0].resource == "mesh"
    assert target_tests[0].details == {"ok": True}
    await engine.dispose()


@pytest.mark.asyncio
async def test_alert_target_route_surfaces_sender_error_and_target_timeout(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'route.sqlite'}")
    await create_database_schema(engine)
    item = mesh_target()
    ConfigStore(tmp_path).save(AppConfig(alert_targets=[item]))
    supervisor = FakeSupervisor()
    app = create_app(_settings(tmp_path), supervisor=supervisor, session_factory=sessions)
    dispatcher = AlertDispatcher(
        AppConfig(alert_targets=[item]), EventBus(), sessions, settings=_settings(tmp_path)
    )
    token = app.state.auth.token
    supervisor.alerts = dispatcher

    class FailingSender:
        async def send(self, _payload: dict[str, object]) -> Any:
            return type("Result", (), {"ok": False, "error": "invented sender failure"})()

    dispatcher._meshtastic["mesh"] = cast("Any", FailingSender())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        failed = await client.post(
            "/api/alert-targets/mesh/test", headers={"Authorization": f"Bearer {token}"}
        )
        assert failed.json() == {"ok": False, "error": "invented sender failure"}

        class SlowSender:
            async def send(self, _payload: dict[str, object]) -> Any:
                await asyncio.sleep(1)
                return type("Result", (), {"ok": True, "error": None})()

        dispatcher._meshtastic["mesh"] = cast("Any", SlowSender())
        timed_out = await client.post(
            "/api/alert-targets/mesh/test", headers={"Authorization": f"Bearer {token}"}
        )
    assert timed_out.json() == {"ok": False, "error": "target timeout"}
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("min_interval_s", "max_per_hour"),
    [(30.0, 20), (0.0, 1)],
)
async def test_dispatcher_rate_limiter_records_one_real_sqlite_row(
    tmp_path: Path, min_interval_s: float, max_per_hour: int
) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'limits.sqlite'}")
    await create_database_schema(engine)
    item = mesh_target().model_copy(
        update={"coalesce_s": 0, "min_interval_s": min_interval_s, "max_per_hour": max_per_hour}
    )
    config = AppConfig(
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=[item.id],
            )
        ],
        alert_targets=[item],
    )

    dispatcher = AlertDispatcher(config, EventBus(), sessions, settings=_settings(tmp_path))

    class Sender(MeshtasticSender):
        async def send(self, _payload: dict[str, object]) -> MeshtasticResult:
            now = __import__("time").monotonic()
            if not self._allowed(now):
                return MeshtasticResult(False, "rate_limited")
            self._last_sent = now
            self._sent.append(now)
            return MeshtasticResult(True)

    dispatcher._meshtastic["mesh"] = Sender(item)
    calls = [Call(started_at=datetime.now(UTC), source_id="radio") for _ in range(2)]
    async with sessions() as session:
        session.add_all(calls)
        await session.commit()
    for call in calls:
        await dispatcher.handle(ToneDetected(call.id, "county-fire", datetime.now(UTC), "radio"))
        pending = tuple(dispatcher._coalescing.values())
        if pending:
            await asyncio.gather(*pending)
    async with sessions() as session:
        rows = list((await session.scalars(select(AlertAttempt).order_by(AlertAttempt.id))).all())
    assert len(rows) == 2
    assert [row.error for row in rows] == [None, "rate_limited"]
    assert [row.attempt_no for row in rows] == [1, 1]
    await engine.dispose()
