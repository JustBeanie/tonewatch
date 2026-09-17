"""Authenticated, bounded WebSocket event and telemetry stream."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, WebSocket
from starlette.requests import HTTPConnection, Request
from starlette.websockets import WebSocketDisconnect

from tonewatch.events import (
    CallEnriched,
    ChannelLevel,
    Event,
    EventBus,
    LiveListenersChanged,
    SpectrumUpdate,
    ToneCandidateObserved,
    ToneDiscovered,
)

router = APIRouter()
MAX_CONNECTIONS = 20
QUEUE_SIZE = 100
_TELEMETRY_TYPES = ("levels", "spectrum:")


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(cast("Any", value)).items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def serialize_event(event: Event) -> dict[str, Any]:
    """Serialize a domain event with explicit event type and JSON-safe fields."""
    if isinstance(event, ToneDiscovered):
        event_type = "tone_discovered"
    elif isinstance(event, CallEnriched):
        event_type = "call_enriched"
    elif isinstance(event, LiveListenersChanged):
        event_type = "live_listeners_changed"
    else:
        event_type = type(event).__name__
    return {"type": event_type, "data": _json_value(event)}


class ClientQueue:
    def __init__(self) -> None:
        self.items: deque[tuple[dict[str, Any], bool]] = deque()
        self.condition = asyncio.Condition()
        self.overflowed = False
        self.topics: set[str] = set()
        self.awaiting_pong = False

    async def put(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type", ""))
        topic = "events"
        if message_type == ChannelLevel.__name__:
            topic = "levels"
        elif message_type == SpectrumUpdate.__name__:
            source_id = str(message.get("data", {}).get("source_id", ""))
            topic = f"spectrum:{source_id}"
        if topic not in self.topics:
            return
        telemetry = message_type in (ChannelLevel.__name__, SpectrumUpdate.__name__)
        async with self.condition:
            if len(self.items) >= QUEUE_SIZE:
                if telemetry:
                    for index, (_old, old_telemetry) in enumerate(self.items):
                        if old_telemetry:
                            del self.items[index]
                            break
                    else:
                        return
                else:
                    for index, (_old, old_telemetry) in enumerate(self.items):
                        if old_telemetry:
                            del self.items[index]
                            break
                    else:
                        self.overflowed = True
                        return
            self.items.append((message, telemetry))
            self.condition.notify()

    async def get(self) -> dict[str, Any]:
        async with self.condition:
            while not self.items:
                await self.condition.wait()
            return self.items.popleft()[0]


class WebSocketHub:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.clients: set[ClientQueue] = set()

    async def add(self, websocket: WebSocket) -> ClientQueue | None:
        if len(self.clients) >= MAX_CONNECTIONS:
            await websocket.close(code=1013)
            return None
        client = ClientQueue()
        self.clients.add(client)
        return client

    def remove(self, client: ClientQueue) -> None:
        self.clients.discard(client)

    async def publish(self, message: dict[str, Any]) -> None:
        await asyncio.gather(*(client.put(message) for client in tuple(self.clients)))


def _authorized(websocket: WebSocket) -> tuple[bool, str | None]:
    request = cast("Request", HTTPConnection(websocket.scope))
    auth = websocket.app.state.auth
    authorization = websocket.headers.get("authorization", "")
    if authorization.startswith("Bearer ") and auth.token == authorization[7:].strip():
        return True, None
    for raw_protocol in websocket.headers.get("sec-websocket-protocol", "").split(","):
        protocol = raw_protocol.strip()
        if protocol.startswith("tonewatch.bearer.") and auth.token == protocol[17:]:
            return True, protocol
    if auth.ingress_valid(request):
        return True, None
    session = auth.session_valid(request)
    if session is None:
        return False, None
    origin = websocket.headers.get("origin")
    origin_host = origin.split("://", 1)[-1].rstrip("/") if origin else ""
    if origin and origin_host != websocket.url.netloc:
        return False, "origin"
    return True, None


async def _event_pump(bus: EventBus, hub: WebSocketHub) -> None:
    subscription = bus.subscribe()
    try:
        async for event in subscription:
            if isinstance(event, ToneCandidateObserved):
                continue
            await hub.publish(serialize_event(event))
    finally:
        bus.unsubscribe(subscription)


async def _sender(websocket: WebSocket, client: ClientQueue) -> None:
    while True:
        if client.overflowed:
            await websocket.close(code=1013)
            return
        await websocket.send_json(await client.get())


async def _heartbeat(
    websocket: WebSocket,
    client: ClientQueue,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    while True:
        await sleep(30)
        if client.awaiting_pong:
            await websocket.close(code=1001)
            return
        client.awaiting_pong = True
        await websocket.send_json({"type": "ping", "data": {}})


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Serve the JSON WebSocket protocol."""
    ok, detail = _authorized(websocket)
    if not ok:
        await websocket.close(code=4403 if detail == "origin" else 4401)
        return
    state_hub = getattr(websocket.app.state, "ws_hub", None)
    if not isinstance(state_hub, WebSocketHub):
        hub = WebSocketHub(websocket.app.state.bus)
        websocket.app.state.ws_hub = hub
        websocket.app.state.ws_pump = asyncio.create_task(_event_pump(hub.bus, hub))
    else:
        hub = state_hub
    client = await hub.add(websocket)
    if client is None:
        return
    await websocket.accept(subprotocol=_authorized(websocket)[1])
    spectrum_topics: set[str] = set()
    sender = asyncio.create_task(_sender(websocket, client))
    heartbeat = asyncio.create_task(_heartbeat(websocket, client))
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "pong":
                client.awaiting_pong = False
                continue
            if message.get("type") != "subscribe":
                continue
            topics = message.get("topics", [])
            if not isinstance(topics, list):
                continue
            client.topics = {topic for topic in topics if isinstance(topic, str)}
            for topic in tuple(spectrum_topics):
                if topic not in topics:
                    source_id = topic[9:]
                    count = max(0, hub.bus.spectrum_subscriber_count(source_id) - 1)
                    hub.bus.set_spectrum_subscribers(source_id, count)
                    spectrum_topics.remove(topic)
            for topic in topics:
                if (
                    isinstance(topic, str)
                    and topic.startswith("spectrum:")
                    and topic not in spectrum_topics
                ):
                    source_id = topic[9:]
                    count = hub.bus.spectrum_subscriber_count(source_id) + 1
                    hub.bus.set_spectrum_subscribers(source_id, count)
                    spectrum_topics.add(topic)
            await websocket.send_json({"type": "subscribed", "data": {"topics": topics}})
    except WebSocketDisconnect:
        return
    finally:
        for topic in spectrum_topics:
            source_id = topic[9:]
            hub.bus.set_spectrum_subscribers(
                source_id, max(0, hub.bus.spectrum_subscriber_count(source_id) - 1)
            )
        sender.cancel()
        heartbeat.cancel()
        await asyncio.gather(sender, heartbeat, return_exceptions=True)
        hub.remove(client)
        if not hub.clients:
            pump = getattr(websocket.app.state, "ws_pump", None)
            if pump is not None:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
                websocket.app.state.ws_pump = None
