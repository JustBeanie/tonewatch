"""Home Assistant Supervisor discovery registration."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import httpx

from tonewatch.config.models import AppConfig, MqttTarget

if TYPE_CHECKING:
    from tonewatch.config.store import ConfigStore

DiscoveryClient = Callable[..., Awaitable[httpx.Response]]
MAX_ATTEMPTS = 3


def ensure_addon_mqtt_target(config: AppConfig, settings: object, store: ConfigStore) -> AppConfig:
    """Persist the one-time Supervisor MQTT target created on add-on first boot."""
    if (
        not getattr(settings, "addon_mode", False)
        or getattr(settings, "mqtt_mode", "supervisor") != "supervisor"
    ):
        return config
    if any(isinstance(target, MqttTarget) for target in config.alert_targets):
        return config
    target = MqttTarget(
        id="home-assistant-mqtt",
        name="Home Assistant MQTT",
        source="supervisor",
        ha_discovery=True,
    )
    updated = AppConfig(
        tone_sets=config.tone_sets,
        sources=config.sources,
        alert_targets=[*config.alert_targets, target],
    )
    store.save(updated)
    return updated


async def register_supervisor_discovery(
    port: int,
    *,
    addon_mode: bool,
    hostname: str = "tonewatch",
    client_factory: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Register once with Supervisor; failures are non-fatal and retried."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not addon_mode or not token:
        return False
    payload = {"service": "tonewatch", "config": {"host": hostname, "port": port}}
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with client_factory() as client:
                response = await client.post(
                    "http://supervisor/discovery",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return True
        except (httpx.HTTPError, OSError):
            if attempt < MAX_ATTEMPTS - 1:
                await sleep(2**attempt)
    return False
