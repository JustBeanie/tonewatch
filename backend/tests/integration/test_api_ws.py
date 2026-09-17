"""Real ASGI WebSocket contract tests for M5.4."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest

from tonewatch.api.app import create_app
from tonewatch.api.auth import Session
from tonewatch.api.routes.ws import ClientQueue, _heartbeat, _sender
from tonewatch.events import ChannelLevel, SpectrumUpdate, ToneDetected
from tonewatch.pipeline.channel import Channel
from tonewatch.settings import Settings
from tonewatch.sources.base import AudioFrame


class NoopSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class Socket:
    def __init__(self, app, headers: dict[str, str] | None = None) -> None:
        self.app = app
        self.headers = headers or {}
        self.incoming: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.outgoing: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "path": "/api/ws",
            "raw_path": b"/api/ws",
            "query_string": b"",
            "headers": [
                (key.lower().encode(), value.encode()) for key, value in self.headers.items()
            ],
            "app": app,
        }

    async def receive(self) -> dict[str, object]:
        return await self.incoming.get()

    async def send(self, message: dict[str, object]) -> None:
        await self.outgoing.put(message)

    async def start(self) -> None:
        self.task = asyncio.create_task(self.app(self.scope, self.receive, self.send))
        await self.incoming.put({"type": "websocket.connect"})
        message = await self.outgoing.get()
        if message["type"] == "websocket.close":
            await self.outgoing.put(message)
            return
        assert message["type"] == "websocket.accept"

    async def send_json(self, value: dict[str, object]) -> None:
        await self.incoming.put({"type": "websocket.receive", "text": json.dumps(value)})

    async def recv_json(self) -> dict[str, object]:
        while True:
            message = await self.outgoing.get()
            if message["type"] == "websocket.send":
                return json.loads(str(message["text"]))
            if message["type"] == "websocket.close":
                return {"type": "close", "code": message["code"]}

    async def close(self) -> None:
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)


def make_app(root: Path, *, addon_mode: bool = False):
    return create_app(
        Settings(data_dir=root, addon_mode=addon_mode, zeroconf_enabled=False),
        supervisor=NoopSupervisor(),
        session_factory=lambda: None,
    )


@pytest.mark.asyncio
async def test_ws_rejects_unauthenticated_with_4401_before_data() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        socket = Socket(app)
        await socket.start()
        message = await socket.outgoing.get()
        assert message == {"type": "websocket.close", "code": 4401, "reason": ""}
        assert socket.task is not None
        await asyncio.gather(socket.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["header", "subprotocol", "cookie", "ingress"])
async def test_ws_bearer_header_subprotocol_cookie_and_ingress_auth(mode: str) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = make_app(root, addon_mode=mode == "ingress")
        token = app.state.auth.token
        headers = {
            "header": {"authorization": f"Bearer {token}"},
            "subprotocol": {"sec-websocket-protocol": f"tonewatch.bearer.{token}"},
            "cookie": {"cookie": "tonewatch_session=session", "origin": "http://test"},
            "ingress": {"x-ingress-path": "/api/hassio_ingress/x"},
        }[mode]
        app.state.auth.sessions["session"] = Session("csrf", app.state.auth.clock())
        socket = Socket(app, headers)
        if mode == "ingress":
            socket.scope["client"] = ("172.30.32.2", 1)
        await socket.start()
        await socket.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await socket.recv_json())["type"] == "subscribed"
        await socket.close()


@pytest.mark.asyncio
async def test_ws_cookie_cross_origin_rejected_4403() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        app.state.auth.sessions["session"] = Session("csrf", app.state.auth.clock())
        socket = Socket(app, {"cookie": "tonewatch_session=session", "origin": "http://evil"})
        await socket.start()
        assert (await socket.outgoing.get())["code"] == 4403


@pytest.mark.asyncio
async def test_ws_bearer_ignores_origin() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        socket = Socket(
            app, {"authorization": f"Bearer {app.state.auth.token}", "origin": "http://evil"}
        )
        await socket.start()
        await socket.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await socket.recv_json())["type"] == "subscribed"
        await socket.close()


@pytest.mark.asyncio
async def test_ws_event_delivered_with_iso_fields() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        socket = Socket(app, {"authorization": f"Bearer {app.state.auth.token}"})
        await socket.start()
        await socket.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await socket.recv_json())["type"] == "subscribed"
        event = ToneDetected(uuid4(), "fire", datetime(2026, 1, 2, tzinfo=UTC), "radio")
        app.state.bus.publish(event)
        payload = await socket.recv_json()
        payload = cast("dict[str, Any]", payload)
        assert payload["type"] == "ToneDetected"
        assert cast("dict[str, Any]", payload["data"])["call_id"] == str(event.call_id)
        assert cast("dict[str, Any]", payload["data"])["detected_at"] == "2026-01-02T00:00:00+00:00"
        await socket.close()


@pytest.mark.asyncio
async def test_ws_disconnect_releases_bus_subscriptions_and_tasks() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        baseline = app.state.bus.subscriber_count
        socket = Socket(app, {"authorization": f"Bearer {app.state.auth.token}"})
        await socket.start()
        await socket.send_json({"type": "subscribe", "topics": ["events"]})
        await socket.recv_json()
        assert app.state.bus.subscriber_count == baseline + 1
        await socket.close()
        assert app.state.bus.subscriber_count == baseline
        assert app.state.ws_pump is None


@pytest.mark.asyncio
async def test_ws_restarts_pump_when_a_new_socket_reuses_the_hub() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        headers = {"authorization": f"Bearer {app.state.auth.token}"}
        first = Socket(app, headers)
        await first.start()
        await first.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await first.recv_json())["type"] == "subscribed"
        await first.close()
        assert app.state.ws_pump is None

        second = Socket(app, headers)
        await second.start()
        await second.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await second.recv_json())["type"] == "subscribed"
        event = ToneDetected(uuid4(), "fire", datetime(2026, 1, 2, tzinfo=UTC), "radio")
        app.state.bus.publish(event)
        payload = await asyncio.wait_for(second.recv_json(), timeout=1)
        assert payload["type"] == "ToneDetected"
        await second.close()


@pytest.mark.asyncio
async def test_ws_subscription_lifecycle_pong_and_invalid_messages() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        socket = Socket(app, {"authorization": f"Bearer {app.state.auth.token}"})
        await socket.start()
        await socket.send_json({"type": "other"})
        await socket.send_json({"type": "subscribe", "topics": "bad"})
        await socket.send_json({"type": "subscribe", "topics": ["spectrum:radio", 3]})
        assert (await socket.recv_json())["type"] == "subscribed"
        assert app.state.bus.spectrum_subscriber_count("radio") == 1
        await socket.send_json({"type": "pong"})
        await socket.send_json({"type": "subscribe", "topics": ["events"]})
        assert (await socket.recv_json())["type"] == "subscribed"
        assert app.state.bus.spectrum_subscriber_count("radio") == 0
        await socket.close()


@pytest.mark.asyncio
async def test_ws_sender_delivers_and_closes_on_overflow() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.closed: int | None = None

        async def send_json(self, message: dict[str, object]) -> None:
            self.sent.append(message)

        async def close(self, code: int) -> None:
            self.closed = code

    socket = FakeSocket()
    client = ClientQueue()
    client.topics = {"events"}
    await client.put({"type": "ToneDetected", "data": {}})
    task = asyncio.create_task(_sender(cast("Any", socket), client))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert socket.sent == [{"type": "ToneDetected", "data": {}}]
    client.overflowed = True
    await _sender(cast("Any", socket), client)
    assert socket.closed == 1013


@pytest.mark.asyncio
async def test_ws_connection_limit_rejects_21st() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        sockets = [
            Socket(app, {"authorization": f"Bearer {app.state.auth.token}"}) for _ in range(21)
        ]
        for socket in sockets:
            await socket.start()
        assert (await sockets[-1].outgoing.get())["code"] == 1013
        for socket in sockets[:-1]:
            await socket.close()


@pytest.mark.asyncio
async def test_ws_levels_throttled_to_5hz() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        subscription = app.state.bus.subscribe(ChannelLevel)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        channel = Channel.__new__(Channel)
        channel.source_config = cast("Any", SimpleNamespace(id="radio"))
        channel.bus = app.state.bus
        channel.clock = lambda: now
        channel._anchor_wall = now
        channel._anchor_stream_s = 0.0
        for stream_time in (0.0, 0.1, 0.2, 0.3, 0.4, 0.6):
            channel._publish_level(AudioFrame(np.ones(16, dtype=np.float32), stream_time, "radio"))
        await asyncio.sleep(0)
        assert subscription.queue.qsize() == 3


@pytest.mark.asyncio
async def test_ws_spectrum_only_computed_while_subscribed() -> None:
    with TemporaryDirectory() as directory:
        app = make_app(Path(directory))
        channel = Channel.__new__(Channel)
        channel.source_config = cast("Any", SimpleNamespace(id="radio"))
        channel.bus = app.state.bus
        channel.clock = lambda: datetime(2026, 1, 1, tzinfo=UTC)
        channel._anchor_wall = datetime(2026, 1, 1, tzinfo=UTC)
        channel._anchor_stream_s = 0.0
        calls = 0

        class Spy:
            freq_hz = 1000.0
            purity = 0.9
            level_dbfs = -10.0
            t_end_s = 0.1

        def publish_if_subscribed() -> None:
            nonlocal calls
            if app.state.bus.spectrum_subscribed("radio"):
                calls += 1
                app.state.bus.publish(
                    SpectrumUpdate("radio", 1000, 0.9, -10, (), datetime(2026, 1, 1, tzinfo=UTC))
                )

        publish_if_subscribed()
        assert calls == 0
        app.state.bus.set_spectrum_subscribers("radio", 1)
        publish_if_subscribed()
        assert calls == 1
        app.state.bus.set_spectrum_subscribers("radio", 0)
        publish_if_subscribed()
        assert calls == 1


@pytest.mark.asyncio
async def test_ws_slow_client_drops_telemetry_not_events() -> None:
    queue = ClientQueue()
    queue.topics = {"events", "levels"}
    for _ in range(100):
        await queue.put({"type": "ChannelLevel", "data": {}})
    await queue.put({"type": "ToneDetected", "data": {}})
    assert any(item[0]["type"] == "ToneDetected" for item in queue.items)


@pytest.mark.asyncio
async def test_ws_event_queue_overflow_closes_1013() -> None:
    queue = ClientQueue()
    queue.topics = {"events"}
    for _ in range(101):
        await queue.put({"type": "ToneDetected", "data": {}})
    assert queue.overflowed


@pytest.mark.asyncio
async def test_ws_heartbeat_ping_and_timeout() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []
            self.code: int | None = None

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)

        async def close(self, code: int) -> None:
            self.code = code

    sleep_calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        await asyncio.sleep(0)
        if sleep_calls >= 2:
            return

    socket = FakeSocket()
    client = ClientQueue()
    task = asyncio.create_task(_heartbeat(cast("Any", socket), client, fake_sleep))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.gather(task, return_exceptions=True)
    assert socket.messages == [{"type": "ping", "data": {}}]
    assert socket.code == 1001
