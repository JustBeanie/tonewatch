"""Wire-level MQTT coverage for the alert publisher and HA discovery."""

from __future__ import annotations

import asyncio
import json
import sys
import warnings
from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import uuid4

import aiomqtt
import pytest

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.config.models import AppConfig, FileSource, MqttTarget, ToneSet, ToneSpec
from tonewatch.events import EventBus, FeedHealthChanged, ToneDetected
from tonewatch.settings import Settings


async def _messages(client: aiomqtt.Client, seconds: float = 3.0) -> list[tuple[str, bytes, bool]]:
    """Collect wire messages for a bounded interval."""
    result: list[tuple[str, bytes, bool]] = []
    deadline = asyncio.get_running_loop().time() + seconds
    while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
        try:
            message = await asyncio.wait_for(client.messages.__anext__(), remaining)
        except TimeoutError:
            break
        result.append((str(message.topic), bytes(message.payload), bool(message.retain)))
    return result


async def _start_broker() -> tuple[Any, int]:
    """Start an anonymous broker on an ephemeral local port."""
    config = {
        "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        broker = import_module("amqtt.broker").Broker(config)
    await broker.start()
    server = broker._servers["default"].instance
    port = int(server.sockets[0].getsockname()[1])
    return broker, port


async def _close_broker(broker: Any) -> None:
    await broker.shutdown()


def _assert_received(received: list[tuple[str, bytes, bool]], call_id: object) -> str:
    availability = [item for item in received if item[0] == "tonewatch/wire-instance/availability"]
    assert any(payload == b"online" and retained for _topic, payload, retained in availability)
    calls = [item for item in received if item[0] == "tonewatch/wire-instance/call"]
    assert calls
    call_payload = json.loads(calls[-1][1])
    assert call_payload["call_id"] == str(call_id)
    assert call_payload["tone_sets"] == ["page"]
    assert call_payload["phase"] == "pre_alert"
    assert call_payload["recording_url"] is None
    # W1a-fix: filesystem paths never leave the host in external payloads.
    assert "recording_path" not in call_payload
    assert call_payload["source_id"] == "radio"
    assert call_payload["test"] is False
    assert call_payload["toneset"] == "page"
    assert any(
        topic == "tonewatch/wire-instance/health/radio" and payload == b"online"
        for topic, payload, _retained in received
    )
    discovery = [item for item in received if item[0].startswith("homeassistant/")]
    assert discovery
    event_configs = [item for item in discovery if "/event/" in item[0] and item[1]]
    assert event_configs and json.loads(event_configs[-1][1])["event_types"] == [
        "pre_alert",
        "recording_ready",
    ]
    assert any("sensor/" in topic and b"last_call" in payload for topic, payload, _ in discovery)
    assert any(
        "binary_sensor/" in topic and b"call_active" in payload for topic, payload, _ in discovery
    )
    assert any("feed_healthy" in topic and b"radio" in payload for topic, payload, _ in discovery)
    return event_configs[-1][0]


async def _assert_deleted_discovery(
    subscriber: aiomqtt.Client, broker: Any, old_event_topic: str
) -> None:
    cleared = await _messages(subscriber, 1.0)
    assert any(topic == old_event_topic and payload == b"" for topic, payload, _ in cleared)
    assert old_event_topic not in broker.retained_messages


async def _run_real_broker_test() -> None:
    broker, port = await _start_broker()
    subscriber: aiomqtt.Client | None = None
    dispatcher: AlertDispatcher | None = None
    try:
        subscriber = aiomqtt.Client(hostname="127.0.0.1", port=port)
        await subscriber.__aenter__()

        target = MqttTarget(id="mqtt", name="MQTT", host="127.0.0.1", port=port)
        config = AppConfig(
            tone_sets=[
                ToneSet(
                    id="page",
                    name="Page",
                    sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                    alert_targets=[target.id],
                )
            ],
            sources=[FileSource(id="radio", name="Radio", path="sample.wav")],
            alert_targets=[target],
        )
        dispatcher = AlertDispatcher(
            config,
            EventBus(),
            settings=Settings(instance_id="wire-instance"),
            instance_id="wire-instance",
        )
        await dispatcher.start()
        await dispatcher._mqtt[target.id]._connected.wait()
        await subscriber.subscribe("tonewatch/#")
        await subscriber.subscribe("homeassistant/#")
        call_id = uuid4()
        await dispatcher.handle(ToneDetected(call_id, "page", datetime.now(UTC), "radio"))
        await dispatcher._health(FeedHealthChanged("radio", True))
        received = await _messages(subscriber)
        old_event_topic = _assert_received(received, call_id)
        await dispatcher.reload(AppConfig(alert_targets=[target]))
        await _assert_deleted_discovery(subscriber, broker, old_event_topic)

        await dispatcher.stop()
        stopped = await _messages(subscriber, 1.0)
        assert any(
            topic == "tonewatch/wire-instance/availability" and payload == b"offline"
            for topic, payload, _retained in stopped
        )
    finally:
        if dispatcher is not None:
            await dispatcher.stop()
        if subscriber is not None:
            await subscriber.__aexit__(None, None, None)
        await _close_broker(broker)


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="aiomqtt requires a selector loop; covered on Linux CI",
)
async def test_mqtt_real_broker_call_health_lwt_and_discovery() -> None:
    """Exercise aiomqtt and HA discovery over a real MQTT socket."""
    await _run_real_broker_test()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-only selector-thread real-broker smoke; Linux wire coverage is above",
)
@pytest.mark.skip(
    reason=(
        "amqtt broker cannot run on the app's Windows Proactor loop; "
        "selector-thread smoke is PENDING-CI"
    ),
)
@pytest.mark.asyncio
async def test_mqtt_real_broker_via_selector_thread() -> None:
    """The Windows CI job runs the real broker smoke on the selector thread."""
    await _run_real_broker_test()
