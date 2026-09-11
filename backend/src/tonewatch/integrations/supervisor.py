"""Home Assistant Supervisor discovery registration."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import httpx

DiscoveryClient = Callable[..., Awaitable[httpx.Response]]
MAX_ATTEMPTS = 3


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
