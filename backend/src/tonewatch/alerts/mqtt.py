"""MQTT alert publisher with reconnecting bounded outbox."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiomqtt
import httpx

from tonewatch.config.models import MqttTarget

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

OUTBOX_SIZE = 100
CLIENT_CLOSE_TIMEOUT_S = 2.0
LOGGER = logging.getLogger("tonewatch.alerts.mqtt")


@dataclass(frozen=True)
class MqttMessage:
    """One queued publication."""

    topic: str
    payload: str
    retain: bool = False


@dataclass(frozen=True)
class SupervisorMqttService:
    """Credentials and connection settings returned by Supervisor."""

    host: str
    port: int
    tls: bool
    username: str = field(repr=False)
    password: str = field(repr=False)
    protocol: str = field(repr=False)


class SupervisorMqttUnavailable(RuntimeError):
    """Supervisor did not provide a usable MQTT service definition."""


async def fetch_supervisor_mqtt(
    *, client_factory: Callable[..., Any] = httpx.AsyncClient
) -> SupervisorMqttService:
    """Fetch the current MQTT service definition without persisting credentials."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
    try:
        async with client_factory(timeout=5.0, trust_env=False) as client:
            response = await client.get(
                "http://supervisor/services/mqtt",
                headers={"Authorization": f"Bearer {token}"},
            )
            status_code = getattr(response, "status_code", 200)
            if status_code in {400, 404}:
                raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
            response.raise_for_status()
            raw = response.json()
    except SupervisorMqttUnavailable:
        raise
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable") from exc
    if not isinstance(raw, dict):
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
    service = raw.get("data", raw)
    if not isinstance(service, dict):
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
    host = service.get("host")
    port = service.get("port")
    tls = service.get("ssl")
    username = service.get("username")
    password = service.get("password")
    protocol = service.get("protocol")
    if isinstance(username, str) and username and isinstance(password, str) and password:
        host = host or "localhost"
        port = 1883 if port is None else port
        tls = False if tls is None else tls
        protocol = protocol or "mqtt"
    if (
        not isinstance(host, str)
        or not host
        or isinstance(port, bool)
        or not isinstance(port, (int, str))
        or not isinstance(tls, bool)
        or not isinstance(username, str)
        or not username
        or not isinstance(password, str)
        or not password
        or not isinstance(protocol, str)
        or not protocol
    ):
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
    try:
        numeric_port = int(port)
    except ValueError as exc:
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable") from exc
    if not 1 <= numeric_port <= 65535:
        raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
    return SupervisorMqttService(host, numeric_port, tls, username, password, protocol)


async def addon_mqtt_credentials(
    *,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> tuple[str, str] | None:
    """Read credentials from Supervisor when running as an add-on."""
    try:
        service = await fetch_supervisor_mqtt(client_factory=client_factory)
    except SupervisorMqttUnavailable:
        return None
    return service.username, service.password


class MqttPublisher:
    """Publish call and health messages while surviving broker restarts."""

    def __init__(
        self,
        target: MqttTarget,
        instance_id: str,
        *,
        addon_mode: bool = False,
        credentials: tuple[str, str] | None = None,
        credential_loader: Callable[[], Awaitable[tuple[str, str] | None]] = addon_mqtt_credentials,
        service_loader: Callable[[], Awaitable[SupervisorMqttService]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        outbox_size: int = OUTBOX_SIZE,
        client_factory: Callable[..., Any] = aiomqtt.Client,
    ) -> None:
        self.target, self.instance_id = target, instance_id
        self.addon_mode, self.credentials = addon_mode, credentials
        self.credential_loader, self.service_loader = credential_loader, service_loader
        self.sleep, self.client_factory = sleep, client_factory
        self.outbox: deque[MqttMessage] = deque(maxlen=outbox_size)
        self._outbox_lock = threading.Lock()
        self.client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._thread_loop: asyncio.AbstractEventLoop | None = None
        self._thread_stop: asyncio.Event | None = None
        self._thread_ready = threading.Event()
        self._thread_connected = threading.Event()
        self.healthy = False
        self.health_reason = "not connected"
        self._unavailable_logged = False

    @property
    def status(self) -> tuple[bool, str]:
        """Return the latest connection state and a user-facing reason."""
        return self.healthy, self.health_reason

    @property
    def availability_topic(self) -> str:
        """Return the retained LWT topic."""
        return f"tonewatch/{self.instance_id}/availability"

    async def start(self) -> None:
        """Start the reconnect loop."""
        if sys.platform == "win32":
            if self._thread is None:
                self._stopping = False
                self._thread_ready.clear()
                self._thread_stop = None
                self._thread = threading.Thread(
                    target=self._run_selector_thread,
                    name=f"tonewatch-mqtt-{self.target.id}",
                    daemon=True,
                )
                self._thread.start()
                await asyncio.to_thread(self._thread_ready.wait, 5.0)
            return
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name=f"tonewatch-mqtt-{self.target.id}")

    async def stop(self) -> None:
        """Publish offline and close the MQTT client."""
        if sys.platform == "win32" and self._thread is not None:
            self._stopping = True
            loop, stop_event, thread = self._thread_loop, self._thread_stop, self._thread
            if loop is not None and stop_event is not None:
                loop.call_soon_threadsafe(stop_event.set)
            if thread is not None:
                await asyncio.to_thread(thread.join, 10.0)
                self._thread = None
            self._thread_loop = None
            self._thread_stop = None
            self._thread_connected.clear()
            self.client = None
            return
        self._stopping = True
        self._mark_unhealthy("stopped")
        self._connected.clear()
        if self.client is not None:
            try:
                await self.client.publish(
                    self.availability_topic, payload="offline", qos=1, retain=True
                )
            except Exception:
                pass
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:
                pass
            self.client = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def publish(self, topic: str, payload: object, *, retain: bool = False) -> None:
        """Publish immediately when connected, otherwise retain in the bounded outbox."""
        message = MqttMessage(
            topic, payload if isinstance(payload, str) else json.dumps(payload), retain
        )
        if sys.platform == "win32" and self._thread is not None:
            loop = self._thread_loop
            if loop is None or not loop.is_running() or not self._thread_connected.is_set():
                self._queue(message)
                return
            try:
                future = asyncio.run_coroutine_threadsafe(self._publish_in_thread(message), loop)
                await asyncio.wrap_future(future)
            except Exception:
                self._queue_left(message)
                self._thread_connected.clear()
            return
        if self.client is None or not self._connected.is_set():
            self._queue(message)
            return
        try:
            await self.client.publish(message.topic, payload=message.payload, qos=1, retain=retain)
        except Exception:
            self._queue_left(message)
            self._connected.clear()
            self._mark_unhealthy("mqtt connection unavailable")

    async def publish_call(self, payload: dict[str, object]) -> None:
        """Publish a call event."""
        await self.publish(f"tonewatch/{self.instance_id}/call", payload)

    async def publish_discovered(self, payload: dict[str, object]) -> None:
        """Publish an opt-in discovery event."""
        await self.publish(f"tonewatch/{self.instance_id}/discovered", payload)

    async def publish_health(self, source_id: str, healthy: bool) -> None:
        """Publish one source health state."""
        state = "online" if healthy else "offline"
        await self.publish(f"tonewatch/{self.instance_id}/health/{source_id}", state)

    def _queue(self, message: MqttMessage) -> None:
        with self._outbox_lock:
            self.outbox.append(message)

    def _queue_left(self, message: MqttMessage) -> None:
        with self._outbox_lock:
            self.outbox.appendleft(message)

    def _pop_queued(self) -> MqttMessage | None:
        with self._outbox_lock:
            return self.outbox.popleft() if self.outbox else None

    def _run_selector_thread(self) -> None:
        """Run aiomqtt on a selector loop because Windows uses a Proactor loop."""
        loop = asyncio.SelectorEventLoop()
        self._thread_loop = loop
        asyncio.set_event_loop(loop)
        self._thread_stop = asyncio.Event()
        self._thread_ready.set()
        try:
            loop.run_until_complete(self._run_client(self._thread_stop))
        finally:
            self._thread_connected.clear()
            self._thread_loop = None
            loop.close()

    async def _publish_in_thread(self, message: MqttMessage) -> None:
        if self.client is None:
            raise RuntimeError("MQTT client is disconnected")
        await self.client.publish(
            message.topic, payload=message.payload, qos=1, retain=message.retain
        )

    async def _run(self) -> None:
        await self._run_client()

    async def _resolve_target(self) -> tuple[str, int, bool, str | None, str | None]:
        if self.target.source == "supervisor":
            if not self.addon_mode:
                raise SupervisorMqttUnavailable("supervisor mqtt target requires add-on mode")
            if self.service_loader is not None:
                service = await self.service_loader()
            elif self.credential_loader is addon_mqtt_credentials:
                service = await fetch_supervisor_mqtt()
            else:
                service = None
            if service is None:
                loaded = await self.credential_loader()
                if loaded is None:
                    raise SupervisorMqttUnavailable("supervisor mqtt service unavailable")
                return (
                    self.target.hostname,
                    self.target.port,
                    self.target.tls,
                    loaded[0],
                    loaded[1],
                )
            return service.host, service.port, service.tls, service.username, service.password
        return (
            self.target.hostname,
            self.target.port,
            self.target.tls,
            self.target.username,
            self.target.password,
        )

    def _mark_healthy(self) -> None:
        self.healthy = True
        self.health_reason = "connected"

    def _mark_unhealthy(self, reason: str) -> None:
        self.healthy = False
        self.health_reason = reason

    def _set_connected(self, connected: bool) -> None:
        if sys.platform == "win32":
            (self._thread_connected.set if connected else self._thread_connected.clear)()
        elif connected:
            self._connected.set()
        else:
            self._connected.clear()

    async def _wait_for_activity(self, stop_event: asyncio.Event | None) -> None:
        if stop_event is None:
            await self.client.messages.__anext__()
            return
        message_task = asyncio.create_task(self.client.messages.__anext__())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            (message_task, stop_task), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _backoff(self, delay: float, stop_event: asyncio.Event | None) -> None:
        if stop_event is None:
            await self.sleep(delay)
            return
        sleep_task: asyncio.Future[Any] = asyncio.ensure_future(self.sleep(delay))
        stop_task = asyncio.create_task(stop_event.wait())
        _done, pending = await asyncio.wait(
            (sleep_task, stop_task), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _connect_once(self, stop_event: asyncio.Event | None) -> None:
        host, port, tls, username, password = await self._resolve_target()
        will = aiomqtt.Will(self.availability_topic, payload="offline", qos=1, retain=True)
        self.client = self.client_factory(
            hostname=host,
            port=port,
            username=username,
            password=password,
            tls_context=ssl.create_default_context() if tls else None,
            will=will,
        )
        await self.client.__aenter__()
        self._mark_healthy()
        await self.client.publish(self.availability_topic, payload="online", qos=1, retain=True)
        while (message := self._pop_queued()) is not None:
            await self.client.publish(
                message.topic, payload=message.payload, qos=1, retain=message.retain
            )
        self._set_connected(True)
        await self._wait_for_activity(stop_event)

    async def _close_client(self) -> None:
        self._set_connected(False)
        if self.client is not None:
            if self._stopping:
                try:
                    await asyncio.wait_for(
                        self.client.publish(
                            self.availability_topic, payload="offline", qos=1, retain=True
                        ),
                        CLIENT_CLOSE_TIMEOUT_S,
                    )
                except Exception:
                    pass
            try:
                await asyncio.wait_for(
                    self.client.__aexit__(None, None, None), CLIENT_CLOSE_TIMEOUT_S
                )
            except Exception:
                pass
            self.client = None

    async def _run_client(self, stop_event: asyncio.Event | None = None) -> None:
        delay = 1.0
        while not self._stopping and not (stop_event is not None and stop_event.is_set()):
            try:
                await self._connect_once(stop_event)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except SupervisorMqttUnavailable as exc:
                self._mark_unhealthy(str(exc))
                if not self._unavailable_logged:
                    LOGGER.warning(
                        "supervisor mqtt service unavailable",
                        extra={"target_id": self.target.id, "reason": str(exc)},
                    )
                    self._unavailable_logged = True
                await self._backoff(min(delay, 30.0), stop_event)
                delay = min(delay * 2, 30.0)
            except Exception:
                self._mark_unhealthy("mqtt connection unavailable")
                self._set_connected(False)
                await self._backoff(min(delay, 30.0), stop_event)
                delay = min(delay * 2, 30.0)
            finally:
                await self._close_client()
