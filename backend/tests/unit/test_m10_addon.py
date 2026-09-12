"""M10 add-on mode regression tests."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import structlog
from pydantic import AnyUrl

import tonewatch.alerts.dispatcher as dispatcher_module
from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.mqtt import (
    MqttPublisher,
    SupervisorMqttService,
    SupervisorMqttUnavailable,
    fetch_supervisor_mqtt,
)
from tonewatch.api.app import create_app
from tonewatch.api.audit import record_audit
from tonewatch.config.models import AppConfig, MqttTarget, ScriptTarget, WebhookTarget
from tonewatch.config.store import ConfigStore
from tonewatch.events import EventBus
from tonewatch.settings import Settings
from tonewatch.storage.db import checkpoint_database


def test_addon_options_are_explicitly_mapped_and_unknown_keys_are_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps(
            {
                "log_level": "debug",
                "public_base_url": "https://example.test/tonewatch/",
                "mqtt_mode": "manual",
                "ui_password": "option-secret-value",
                "future_key": "do-not-use",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token-value")
    logged: list[tuple[str, dict[str, object]]] = []

    class Logger:
        def warning(self, event: str, **kwargs: object) -> None:
            logged.append((event, kwargs))

    monkeypatch.setattr(structlog, "get_logger", lambda _name: Logger())
    settings = Settings.load(options_path=options)
    assert settings.log_level == "debug"
    assert settings.public_base_url == "https://example.test/tonewatch"
    assert settings.mqtt_mode == "manual"
    assert settings.ui_password == "option-secret-value"  # noqa: S105 -- fake test credential.
    assert logged == [("unknown add-on options ignored", {"keys": ["future_key"]})]
    assert "option-secret-value" not in repr(settings)


@pytest.mark.parametrize(
    ("key", "value"),
    [("log_level", "trace"), ("mqtt_mode", "automatic"), ("public_base_url", "ftp://x")],
)
def test_invalid_addon_option_names_are_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({key: value}), encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    with pytest.raises(ValueError, match=key):
        Settings.load(options_path=options)


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.test",
        "https://user:pass@example.test",
        "https://example.test/path?token=secret",
        "https://example.test/path#fragment",
    ],
)
def test_public_base_url_rejects_unsafe_urls(value: str) -> None:
    with pytest.raises(ValueError, match="public_base_url"):
        Settings(public_base_url=value)


def test_public_base_url_environment_overrides_addon_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"public_base_url": "https://option.test/"}), encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    monkeypatch.setenv("TONEWATCH_PUBLIC_BASE_URL", "https://env.test/base/")
    settings = Settings.load(options_path=options)
    assert settings.public_base_url == "https://env.test/base"


def test_mqtt_target_source_and_config_lint() -> None:
    target = MqttTarget(id="supervisor", name="Supervisor", source="supervisor")
    assert target.source == "supervisor"
    assert any(
        "requires add-on mode" in warning for warning in AppConfig(alert_targets=[target]).lint()
    )


def _supervisor_response(data: dict[str, object], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json={"data": data})


def test_supervisor_mqtt_fetch_uses_bearer_and_resolves_all_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), dict(request.headers)))
        return _supervisor_response(
            {
                "host": "172.30.32.4",
                "port": 8883,
                "ssl": True,
                "username": "mqtt-user",
                "password": "mqtt-password-value",
                "protocol": "3.1.1",
            }
        )

    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token-value")
    service = asyncio.run(
        fetch_supervisor_mqtt(
            client_factory=lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
    )
    assert service == SupervisorMqttService(
        "172.30.32.4", 8883, True, "mqtt-user", "mqtt-password-value", "3.1.1"
    )
    assert calls[0][0] == "http://supervisor/services/mqtt"
    assert calls[0][1]["authorization"] == "Bearer supervisor-token-value"


def test_supervisor_mqtt_no_service_is_typed_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token-value")

    def handler(_request: httpx.Request) -> httpx.Response:
        return _supervisor_response({}, 404)

    with pytest.raises(SupervisorMqttUnavailable, match="supervisor mqtt service unavailable"):
        asyncio.run(
            fetch_supervisor_mqtt(
                client_factory=lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            )
        )


def test_mqtt_reconnect_refetches_rotated_supervisor_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr("tonewatch.alerts.mqtt.sys.platform", "linux")
        services = iter(
            [
                SupervisorMqttService("broker-a", 1883, False, "user-a", "pass-a", "3.1.1"),
                SupervisorMqttService("broker-b", 8883, True, "user-b", "pass-b", "3.1.1"),
            ]
        )
        factory_calls: list[dict[str, object]] = []
        activity_calls = 0
        stop = asyncio.Event()

        class Client:
            def __init__(self, **kwargs: object) -> None:
                factory_calls.append(kwargs)
                self.messages = self

            async def __aenter__(self) -> "Client":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def publish(self, *_args: object, **_kwargs: object) -> None:
                return None

            async def __anext__(self) -> None:
                nonlocal activity_calls
                activity_calls += 1
                if activity_calls == 2:
                    stop.set()
                raise RuntimeError

        async def loader() -> SupervisorMqttService:
            return next(services)

        publisher = MqttPublisher(
            MqttTarget(id="mqtt", name="MQTT", source="supervisor"),
            "instance",
            addon_mode=True,
            service_loader=loader,
            client_factory=Client,
            sleep=lambda _delay: asyncio.sleep(0),
        )
        publisher._stopping = False
        await publisher._run_client(stop)
        assert factory_calls[0]["hostname"] == "broker-a"
        assert factory_calls[0]["port"] == 1883
        assert factory_calls[0]["username"] == "user-a"
        assert factory_calls[1]["hostname"] == "broker-b"
        assert factory_calls[1]["port"] == 8883
        assert factory_calls[1]["username"] == "user-b"
        assert factory_calls[1]["tls_context"] is not None

    asyncio.run(run())


def test_addon_first_boot_creates_supervisor_target_once(tmp_path: Path) -> None:
    class NoopSupervisor:
        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def reload(self, _config: AppConfig) -> None:
            return None

    async def run() -> None:
        settings = Settings(data_dir=tmp_path, addon_mode=True, zeroconf_enabled=False)
        app = create_app(settings, supervisor=NoopSupervisor(), session_factory=lambda: None)
        async with app.router.lifespan_context(app):
            target = next(item for item in app.state.config.alert_targets if item.type == "mqtt")
            assert isinstance(target, MqttTarget)
            assert target.source == "supervisor"
            assert target.ha_discovery is True
            assert (tmp_path / "config.yaml.bak").exists()
        first = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        app = create_app(settings, supervisor=NoopSupervisor(), session_factory=lambda: None)
        async with app.router.lifespan_context(app):
            assert len(app.state.config.alert_targets) == 1
        assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == first

    asyncio.run(run())


def test_mqtt_off_does_not_start_configured_target() -> None:
    async def run() -> None:
        target = MqttTarget(id="mqtt", name="MQTT")
        dispatcher = AlertDispatcher(
            AppConfig(alert_targets=[target]), EventBus(), settings=Settings(mqtt_mode="off")
        )
        await dispatcher.start()
        assert dispatcher._mqtt == {}
        await dispatcher.stop()

    asyncio.run(run())


def test_recording_payloads_use_absolute_or_explicit_relative_url() -> None:
    call_id = uuid4()
    state = {"tone_sets": ["page"], "source_id": "radio", "test": False}
    relative = AlertDispatcher._payload(
        call_id, "recording_ready", state, False, None, recording_id=4
    )
    absolute = AlertDispatcher._payload(
        call_id,
        "recording_ready",
        state,
        False,
        None,
        recording_id=4,
        public_base_url="https://host.test/tonewatch",
    )
    assert relative["recording_url"] == "/api/recordings/4"
    assert relative["recording_path_relative"] is True
    assert absolute["recording_url"] == "https://host.test/tonewatch/api/recordings/4"
    assert "recording_path_relative" not in absolute


def test_recording_url_reaches_webhook_mqtt_and_script_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        call_id = uuid4()
        target_mqtt = MqttTarget(id="mqtt", name="MQTT")
        target_webhook = WebhookTarget(
            id="webhook", name="Webhook", url=AnyUrl("https://example.test")
        )
        target_script = ScriptTarget(
            id="script", name="Script", executable="/bin/true", args=["{recording_url}"]
        )
        dispatcher = AlertDispatcher(
            AppConfig(alert_targets=[target_mqtt, target_webhook, target_script]),
            EventBus(),
            settings=Settings(public_base_url="https://host.test/tonewatch"),
        )
        payload = dispatcher._payload(
            call_id,
            "recording_ready",
            {"tone_sets": ["page"], "source_id": "radio", "test": False},
            False,
            None,
            recording_id=4,
            public_base_url=dispatcher.settings.public_base_url,
        )
        sent: list[dict[str, object]] = []

        class Publisher:
            async def publish_call(self, value: dict[str, object]) -> None:
                sent.append(value)

        dispatcher._mqtt[target_mqtt.id] = cast("MqttPublisher", Publisher())
        await dispatcher._send(target_mqtt, payload)
        assert sent[0]["recording_url"] == "https://host.test/tonewatch/api/recordings/4"

        webhook_values: list[dict[str, object]] = []

        async def fake_webhook(*args: object, **_kwargs: object) -> object:
            webhook_values.append(cast("dict[str, object]", args[1]))
            return type("Result", (), {"ok": True})()

        monkeypatch.setattr(dispatcher_module, "send_webhook", fake_webhook)
        await dispatcher._send(target_webhook, payload)
        assert webhook_values[0]["recording_url"] == "https://host.test/tonewatch/api/recordings/4"

        script_values: list[dict[str, object]] = []

        async def fake_script(*args: object, **_kwargs: object) -> object:
            script_values.append(cast("dict[str, object]", args[1]))
            return type("Result", (), {"ok": True})()

        monkeypatch.setattr(dispatcher_module, "run_script", fake_script)
        await dispatcher._send(target_script, payload)
        assert script_values[0]["recording_url"] == "https://host.test/tonewatch/api/recordings/4"

    asyncio.run(run())


def test_script_recording_url_placeholder_is_supported() -> None:
    target = ScriptTarget(
        id="script", name="Script", executable="/bin/true", args=["{recording_url}"]
    )
    assert target.args == ["{recording_url}"]


def test_api_and_audit_never_expose_supervisor_credentials(tmp_path: Path) -> None:
    async def run() -> None:
        class NoopSupervisor:
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            async def reload(self, _config: AppConfig) -> None:
                return None

        ConfigStore(tmp_path).save(
            AppConfig(
                alert_targets=[
                    MqttTarget(
                        id="mqtt",
                        name="MQTT",
                        source="supervisor",
                        password="resolved-password-value",  # noqa: S106 -- fake test credential.
                    )
                ]
            )
        )
        app = create_app(
            Settings(data_dir=tmp_path),
            supervisor=NoopSupervisor(),
            session_factory=lambda: None,
        )
        token = app.state.auth.token
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            response = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert "resolved-password-value" not in response.text
        captured: list[Any] = []

        class Session:
            def add(self, value: Any) -> None:
                captured.append(value)

            async def commit(self) -> None:
                return None

        class Context:
            async def __aenter__(self) -> Session:
                return Session()

            async def __aexit__(self, *_args: object) -> None:
                return None

        def factory() -> Context:
            return Context()

        await record_audit(
            factory,
            actor="test",
            event_type="config_change",
            resource="config",
            after={"password": "resolved-password-value"},
        )
        assert "resolved-password-value" not in str(captured)

    asyncio.run(run())


def test_checkpoint_retries_with_live_wal_database(tmp_path: Path) -> None:
    path = tmp_path / "tonewatch.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE calls (id INTEGER PRIMARY KEY, value TEXT)")
    connection.commit()
    connection.execute("INSERT INTO calls(value) VALUES ('live')")
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    result: list[tuple[int, int, int]] = []

    async def run() -> None:
        class NoopSupervisor:
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            async def reload(self, _config: AppConfig) -> None:
                return None

        app = create_app(
            Settings(data_dir=tmp_path, addon_mode=True, zeroconf_enabled=False),
            supervisor=NoopSupervisor(),
            session_factory=lambda: None,
        )
        async with app.router.lifespan_context(app):
            task = asyncio.create_task(asyncio.to_thread(checkpoint_database, path, 0.05))
            await asyncio.sleep(0.01)
            connection.rollback()
            result.append(await task)

    asyncio.run(run())
    connection.close()
    assert result and result[0][0] == 0
    with closing(sqlite3.connect(path)) as check:
        assert check.execute("SELECT value FROM calls").fetchone() == ("live",)
