"""M5b proving tests for the live API contracts."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from tonewatch.api.auth import AuthState, Session
from tonewatch.api.routes.ws import (
    ClientQueue,
    WebSocketHub,
    _authorized,
    _json_value,
    serialize_event,
)
from tonewatch.api.ws_models import SubscribeMessage, SubscriptionAck
from tonewatch.events import EventBus, ToneDetected
from tonewatch.integrations.zeroconf import instance_id


def test_serialize_event_uses_iso_fields() -> None:
    event = ToneDetected(uuid4(), "fire", datetime(2026, 1, 2, tzinfo=UTC), "radio")
    payload = serialize_event(event)
    assert payload["type"] == "ToneDetected"
    assert payload["data"]["call_id"] == str(event.call_id)
    assert payload["data"]["detected_at"] == "2026-01-02T00:00:00+00:00"
    assert _json_value((1, 2)) == [1, 2]
    assert _json_value([1, 2]) == [1, 2]


def test_websocket_authentication_modes() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = __import__("tonewatch.settings", fromlist=["Settings"]).Settings(data_dir=root)
        auth = AuthState(settings)
        app = SimpleNamespace(state=SimpleNamespace(auth=auth))
        scope: dict[str, Any] = {
            "type": "websocket",
            "scheme": "ws",
            "server": ("test", 80),
            "client": ("1", 1),
            "path": "/api/ws",
            "headers": [],
            "query_string": b"",
        }
        ws = SimpleNamespace(
            app=app,
            scope=scope,
            headers={"authorization": f"Bearer {auth.token}"},
            url=SimpleNamespace(netloc="test:80"),
        )
        assert _authorized(cast("Any", ws)) == (True, None)
        ws.headers = {"sec-websocket-protocol": f"tonewatch.bearer.{auth.token}"}
        assert _authorized(cast("Any", ws)) == (True, f"tonewatch.bearer.{auth.token}")
        ws.headers = {}
        assert _authorized(cast("Any", ws)) == (False, None)
        auth.sessions["session"] = Session("csrf", auth.clock())
        ws.headers = {"origin": "http://evil"}
        scope["headers"] = [(b"cookie", b"tonewatch_session=session")]
        assert _authorized(cast("Any", ws)) == (False, "origin")


def test_instance_id_is_stable_and_token_free() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        first = instance_id(root)
        assert instance_id(root) == first
        assert "token" not in (root / "instance_id").read_text(encoding="ascii")


def test_websocket_models_define_generated_protocol() -> None:
    assert SubscribeMessage.model_json_schema()["properties"]["topics"]["type"] == "array"
    assert SubscriptionAck().type == "subscribed"


async def _queue_behavior() -> None:
    queue = ClientQueue()
    queue.topics = {"events", "levels"}
    for index in range(100):
        await queue.put({"type": "ChannelLevel", "data": {"value": index}})
    await queue.put({"type": "ToneDetected", "data": {"value": 1}})
    assert queue.items[-1][0]["type"] == "ToneDetected"
    spectrum = ClientQueue()
    spectrum.topics = {"spectrum:radio"}
    update = {"type": "SpectrumUpdate", "data": {"source_id": "radio"}}
    await spectrum.put(update)
    assert spectrum.items[-1][0] == update
    events = ClientQueue()
    events.topics = {"events"}
    for _ in range(100):
        await events.put({"type": "ToneDetected", "data": {}})
    await events.put({"type": "ToneDetected", "data": {}})
    assert events.overflowed


def test_slow_client_retains_events() -> None:
    asyncio.run(_queue_behavior())


def test_hub_limits_connections_and_removes_clients() -> None:
    class Socket:
        async def close(self, code: int) -> None:
            self.code = code

    async def run() -> None:
        hub = WebSocketHub(EventBus())
        clients = []
        for _ in range(20):
            client = await hub.add(cast("Any", Socket()))
            assert client is not None
            clients.append(client)
        extra_socket = Socket()
        assert await hub.add(cast("Any", extra_socket)) is None
        assert extra_socket.code == 1013
        hub.remove(clients[0])

    asyncio.run(run())
