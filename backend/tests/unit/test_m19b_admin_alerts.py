"""M19.2 admin-alert contracts."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import AnyUrl

from tonewatch.admin.alerts import AdminAlertEngine
from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.api.app import create_app
from tonewatch.config.models import (
    AdminAlertsConfig,
    AlertTarget,
    AppConfig,
    MqttTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.config.store import ConfigStore
from tonewatch.events import EventBus, ToneDetected
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.settings import Settings


class _Dispatcher:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.bus = EventBus()

    async def dispatch_admin(self, payload: dict[str, object], _targets: object) -> None:
        self.sent.append(payload)


def test_admin_alert_config_defaults_and_bounds() -> None:
    config = AdminAlertsConfig()
    assert config.enabled is False
    assert config.feed_unhealthy_min == 5
    assert config.realtime_factor_min_s == 300
    with pytest.raises(ValueError, match="feed_unhealthy_min"):
        AdminAlertsConfig(feed_unhealthy_min=0)
    with pytest.raises(ValueError, match="max_per_hour"):
        AdminAlertsConfig(max_per_hour=101)
    with pytest.raises(ValueError, match="extra"):
        AdminAlertsConfig.model_validate({"unexpected": True})


def test_m19b_a_api_rejects_each_invalid_admin_threshold() -> None:
    async def run() -> None:
        invalid = {
            "disk_used_pct": 49,
            "target_failures": 1,
            "realtime_factor_min": 0.9,
            "max_per_hour": 0,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(Settings(data_dir=root))
            token = (root / "api_token").read_text(encoding="ascii").strip()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                for field, value in invalid.items():
                    payload = AppConfig().model_dump(mode="json")
                    payload["admin_alerts"][field] = value
                    response = await client.put(
                        "/api/config",
                        json=payload,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    assert response.status_code == 422
                    assert field in response.text

    asyncio.run(run())


def test_m19b_a_pre_m19b_yaml_loads_with_admin_alerts_off() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "config.yaml").write_text("tone_sets: []\nsources: []\nalert_targets: []\n")
        loaded = ConfigStore(root).load()
        assert loaded.admin_alerts.enabled is False
        assert loaded.model_dump(exclude={"admin_alerts"}) == AppConfig().model_dump(
            exclude={"admin_alerts"}
        )


def test_admin_target_reference_is_validated() -> None:
    with pytest.raises(ValueError, match="missing alert target"):
        AppConfig.model_validate({"admin_alerts": {"enabled": True, "targets": ["missing"]}})
    target = MqttTarget(id="ops", name="Ops")
    config = AppConfig(alert_targets=[target], admin_alerts=AdminAlertsConfig(targets=["ops"]))
    assert config.admin_alerts.targets == ["ops"]


def test_m19b_h_same_tick_deduplicates_notification() -> None:
    async def run() -> None:
        now = [60.0]
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"], disk_used_pct=90),
            dispatcher,
            clock=lambda: now[0],
        )
        snapshot = {"sources": {}, "outputs": {}, "disk": {"used_pct": 95}}
        await asyncio.gather(engine.evaluate(snapshot), engine.evaluate(snapshot))
        assert len(dispatcher.sent) == 1
        assert dispatcher.sent[0]["condition"] == "disk_used"

    asyncio.run(run())


def test_m19b_c_disk_used_and_forecast_have_distinct_resolutions() -> None:
    async def run() -> None:
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"]), dispatcher, clock=lambda: 60.0
        )
        high = {"sources": {}, "outputs": {}, "disk": {"used_pct": 95}, "forecast_days": 2}
        await engine.evaluate(high)
        assert {item["condition"] for item in dispatcher.sent} == {"disk_used", "disk_forecast"}
        await engine.evaluate(
            {"sources": {}, "outputs": {}, "disk": {"used_pct": 40}, "forecast_days": 9}
        )
        assert [item["state"] for item in dispatcher.sent] == [
            "firing",
            "firing",
            "resolved",
            "resolved",
        ]

    asyncio.run(run())


def test_m19b_d_target_failures_fires_once_and_resolves() -> None:
    async def run() -> None:
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"], target_failures=2),
            dispatcher,
            clock=lambda: 60.0,
        )
        failed = {
            "sources": {},
            "outputs": {"ops": SimpleNamespace(consecutive_failures=2)},
            "disk": {},
        }
        await engine.evaluate(failed)
        await engine.evaluate(failed)
        await engine.evaluate(
            {"sources": {}, "outputs": {"ops": SimpleNamespace(consecutive_failures=0)}, "disk": {}}
        )
        assert [(item["condition"], item["state"]) for item in dispatcher.sent] == [
            ("target_failures:ops", "firing"),
            ("target_failures:ops", "resolved"),
        ]

    asyncio.run(run())


def test_m19b_e_squelch_stuck_open_fires_and_resolves() -> None:
    async def run() -> None:
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"]), dispatcher, clock=lambda: 60.0
        )
        engine.squelch_stuck["radio"] = True
        metric = SimpleNamespace(feed_health_history=[])
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        engine.squelch_stuck["radio"] = False
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        assert [
            (item["condition"], item["state"])
            for item in dispatcher.sent
            if "squelch" in str(item["condition"])
        ] == [
            ("squelch_stuck_open:radio", "firing"),
            ("squelch_stuck_open:radio", "resolved"),
        ]

    asyncio.run(run())


def test_m19b_f_realtime_factor_hysteresis_fires_and_resolves() -> None:
    async def run() -> None:
        now = [0.0]
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"], realtime_factor_min_s=30),
            dispatcher,
            clock=lambda: now[0],
        )
        metric = SimpleNamespace(feed_health_history=[], factor=SimpleNamespace(value=1.0))
        snapshot = {"sources": {"radio": metric}, "outputs": {}, "disk": {}}
        await engine.evaluate(snapshot)
        now[0] = 20
        await engine.evaluate(snapshot)
        assert dispatcher.sent == []
        now[0] = 30
        await engine.evaluate(snapshot)
        metric.factor.value = 2.0
        await engine.evaluate(snapshot)
        assert [(item["condition"], item["state"]) for item in dispatcher.sent] == [
            ("realtime_factor:radio", "firing"),
            ("realtime_factor:radio", "resolved"),
        ]

    asyncio.run(run())


def test_m19b_i_admin_payloads_contain_no_webhook_or_mqtt_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        webhook_credential = "webhook-password"
        mqtt_credential = "mqtt-password"
        targets: list[AlertTarget] = [
            WebhookTarget(
                id="hook",
                name="Hook",
                url=AnyUrl(f"https://user:{webhook_credential}@example.test/hook"),
                secret=webhook_credential,
            ),
            MqttTarget(id="mqtt", name="MQTT", password=mqtt_credential),
        ]
        app_config = AppConfig(
            alert_targets=targets,
            admin_alerts=AdminAlertsConfig(enabled=True, targets=["hook", "mqtt"]),
        )
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            app_config.admin_alerts,
            dispatcher,
            clock=lambda: 60.0,
        )
        await engine.evaluate({"sources": {}, "outputs": {}, "disk": {"used_pct": 95}})
        serialized = json.dumps(dispatcher.sent)
        assert webhook_credential not in serialized
        assert mqtt_credential not in serialized
        assert webhook_credential not in caplog.text
        assert mqtt_credential not in caplog.text

    asyncio.run(run())


def test_m19b_j_pages_payloads_are_identical_with_admin_alerts_on_or_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        target = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test"))
        toneset = ToneSet(
            id="page",
            name="Page",
            sequence=[ToneSpec(freq_hz=500, min_s=1)],
            alert_targets=["hook"],
        )
        page_payloads: list[list[dict[str, object]]] = []
        admin_payloads: list[dict[str, object]] = []
        call_id = uuid4()
        for enabled in (False, True):
            config = AppConfig(
                tone_sets=[toneset],
                alert_targets=[target],
                admin_alerts=AdminAlertsConfig(enabled=enabled, targets=["hook"]),
            )
            dispatcher = AlertDispatcher(config, EventBus())
            recorded: list[dict[str, object]] = []

            async def send(
                _target: object,
                payload: dict[str, object],
                captured: list[dict[str, object]] = recorded,
                **_kwargs: object,
            ) -> object:
                captured.append(payload)
                return SimpleNamespace(ok=True, status_code=204, error=None)

            monkeypatch.setattr(dispatcher, "_send", send)
            if enabled:

                async def send_admin(
                    _target: object,
                    payload: dict[str, object],
                    captured: list[dict[str, object]] = admin_payloads,
                ) -> object:
                    captured.append(payload)
                    return SimpleNamespace(ok=True, status_code=204, error=None)

                monkeypatch.setattr(dispatcher, "_send_admin", send_admin)
                engine = AdminAlertEngine(config.admin_alerts, dispatcher, clock=lambda: 60.0)
                await engine.evaluate({"sources": {}, "outputs": {}, "disk": {"used_pct": 95}})
            await dispatcher.handle(
                ToneDetected(call_id, "page", datetime(2026, 1, 1, tzinfo=UTC), "radio")
            )
            page_payloads.append(recorded)
        assert len(page_payloads[0]) == 1
        assert len(page_payloads[1]) == 1
        assert page_payloads[0] == page_payloads[1]
        assert len(admin_payloads) == 1
        assert all(payload.get("kind") != "admin" for payload in page_payloads[1])

    asyncio.run(run())


def test_admin_edges_hysteresis_and_resolution() -> None:
    async def run() -> None:
        now = [0.0]
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(
            AdminAlertsConfig(enabled=True, targets=["ops"], feed_unhealthy_min=1),
            dispatcher,
            clock=lambda: now[0],
        )
        metric = SimpleNamespace(feed_health_history=[{"healthy": False}])
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        assert dispatcher.sent == []
        now[0] = 60
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        assert [item["state"] for item in dispatcher.sent] == ["firing"]
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        assert len(dispatcher.sent) == 1
        metric.feed_health_history = [{"healthy": True}]
        await engine.evaluate({"sources": {"radio": metric}, "outputs": {}, "disk": {}})
        assert [item["state"] for item in dispatcher.sent] == ["firing", "resolved"]
        assert all(item["kind"] == "admin" for item in dispatcher.sent)

    asyncio.run(run())


def test_admin_engine_lifecycle_clears_when_disabled() -> None:
    async def run() -> None:
        dispatcher = _Dispatcher()
        engine = AdminAlertEngine(AdminAlertsConfig(enabled=True), dispatcher)
        await engine.start()
        await engine.reload(AdminAlertsConfig(enabled=False))
        assert engine.latches == {}
        await engine.stop()

    asyncio.run(run())


def test_admin_conditions_rate_cap_and_supervisor_timer() -> None:
    async def run() -> None:
        now = [0.0]
        dispatcher = _Dispatcher()
        config = AdminAlertsConfig(
            enabled=True,
            targets=["ops"],
            feed_unhealthy_min=1,
            realtime_factor_min_s=30,
            min_interval_s=60,
            max_per_hour=6,
        )
        engine = AdminAlertEngine(config, dispatcher, clock=lambda: now[0])
        metric = SimpleNamespace(
            feed_health_history=[{"healthy": False}],
            factor=SimpleNamespace(value=1.0),
        )
        output = SimpleNamespace(consecutive_failures=5)
        snapshot = {
            "sources": {"radio": metric},
            "outputs": {"ops": output},
            "feed_healthy": {"radio": False},
            "disk": {"used_pct": 95},
            "forecast_days": 2,
        }
        await engine.evaluate(snapshot)
        now[0] = 360
        await engine.evaluate(snapshot)
        assert any(item["condition"] == "disk_used" for item in dispatcher.sent)
        assert any(item["condition"] == "target_failures:ops" for item in dispatcher.sent)
        assert sum(state.dropped for state in engine.latches.values()) > 0

        async def stop_sleep(_seconds: float) -> None:
            raise asyncio.CancelledError

        supervisor = Supervisor(
            AppConfig(alert_targets=[MqttTarget(id="ops", name="Ops")], admin_alerts=config),
            EventBus(),
            None,
            sleep=stop_sleep,
            settings=None,
        )
        supervisor._admin_scanner = None
        with pytest.raises(asyncio.CancelledError):
            await supervisor._admin_loop()

        class Scanner:
            async def scan(self) -> dict[str, object]:
                return {"free_bytes": 1000, "total_bytes": 2000}

        class Result:
            def all(self) -> list[tuple[datetime, int]]:
                stamp = datetime(2026, 1, 1, tzinfo=UTC)
                return [(stamp, 100), (stamp + timedelta(days=1), 100)]

        class Session:
            async def __aenter__(self) -> "Session":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def execute(self, _query: object) -> Result:
                return Result()

        def session_factory() -> Session:
            return Session()

        supervisor._admin_scanner = cast("Any", Scanner())
        supervisor.session_factory = session_factory
        with pytest.raises(asyncio.CancelledError):
            await supervisor._admin_loop()

    asyncio.run(run())


def test_admin_dispatch_uses_separate_sender_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        target = WebhookTarget(id="ops", name="Ops", url=AnyUrl("https://example.test"))
        dispatcher = AlertDispatcher(AppConfig(alert_targets=[target]), EventBus())
        calls: list[dict[str, object]] = []

        async def send(_target: object, payload: dict[str, object]) -> object:
            calls.append(payload)
            return SimpleNamespace(ok=True, status_code=204, error=None)

        monkeypatch.setattr(dispatcher, "_send_admin", send)
        await dispatcher.dispatch_admin({"kind": "admin", "condition": "disk_used"}, ["ops"])
        assert calls == [{"kind": "admin", "condition": "disk_used"}]

    asyncio.run(run())
