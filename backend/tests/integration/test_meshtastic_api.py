"""M18a Meshtastic API, audit, and dispatcher integration coverage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from sqlalchemy import select

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.meshtastic import MeshtasticResult, MeshtasticSender
from tonewatch.api.app import create_app
from tonewatch.config.models import AppConfig, MeshtasticTarget, ToneSet, ToneSpec
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
    app = create_app(Settings(data_dir=tmp_path), supervisor=supervisor, session_factory=sessions)
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
        updated = dict(payload, name="Renamed Mesh")
        response = await client.put("/api/alert-targets/mesh", headers=headers, json=updated)
        assert response.status_code == 200
    async with sessions() as session:
        audits = list((await session.scalars(select(AuditEvent))).all())
    assert audits
    assert "invented-mesh-password" not in str(audits)
    await engine.dispose()


@pytest.mark.asyncio
async def test_alert_target_route_uses_real_dispatcher_without_attempt_rows(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'dispatcher.sqlite'}")
    await create_database_schema(engine)
    item = mesh_target()
    ConfigStore(tmp_path).save(AppConfig(alert_targets=[item]))
    supervisor = FakeSupervisor()
    app = create_app(Settings(data_dir=tmp_path), supervisor=supervisor, session_factory=sessions)
    dispatcher = AlertDispatcher(
        AppConfig(alert_targets=[item]), EventBus(), sessions, settings=Settings()
    )
    sent = 0

    class Sender:
        async def send(self, _payload: dict[str, object]) -> Any:
            nonlocal sent
            sent += 1
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
    app = create_app(Settings(data_dir=tmp_path), supervisor=supervisor, session_factory=sessions)
    dispatcher = AlertDispatcher(
        AppConfig(alert_targets=[item]), EventBus(), sessions, settings=Settings()
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

    dispatcher = AlertDispatcher(config, EventBus(), sessions, settings=Settings())

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
