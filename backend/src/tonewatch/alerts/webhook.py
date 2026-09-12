"""Signed, SSRF-safe webhook delivery."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from tonewatch.alerts.urlsafety import (
    PinnedIPTransport,
    ResolvedURL,
    UnsafeURL,
    resolve_and_validate,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tonewatch.config.models import WebhookTarget
    from tonewatch.settings import Settings

MAX_RESPONSE_BYTES = 64 * 1024


def _safe_error(value: str, secret: str) -> str:
    """Bound errors while ensuring a receiver cannot reflect the webhook secret."""
    return value.replace(secret, "[redacted]")[:500]


@dataclass(frozen=True)
class WebhookResult:
    """Outcome returned to the dispatcher without sensitive data."""

    ok: bool
    status_code: int | None = None
    error: str | None = None


def signature(secret: str, timestamp: str, body: bytes) -> str:
    """Return the receiver-verifiable ToneWatch signature."""
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def _recording_attachment(
    local_attachment_path: str | None,
    settings: Settings,
) -> tuple[str, bytes, str] | None:
    """Read an optional recording only after applying the recordings-route path check."""
    if not local_attachment_path:
        return None
    root = settings.recording_path
    try:
        path = Path(local_attachment_path).resolve(strict=True)
        path.relative_to(root)
        if not path.is_file() or path.stat().st_size > settings.webhook_attachment_max_bytes:
            return None
        suffix = path.suffix or ".bin"
        media = {".mp3": "audio/mpeg", ".opus": "audio/ogg", ".ogg": "audio/ogg"}.get(
            suffix.lower(), "application/octet-stream"
        )
        return path.name, path.read_bytes(), media
    except (FileNotFoundError, OSError, ValueError):
        return None


async def _read_limited(response: httpx.Response) -> bytes:
    """Consume at most the configured response limit."""
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) >= MAX_RESPONSE_BYTES:
            return bytes(data[:MAX_RESPONSE_BYTES])
    return bytes(data)


async def send_webhook(
    target: WebhookTarget,
    payload: dict[str, Any],
    settings: Settings,
    *,
    local_attachment_path: str | None = None,
    timestamp: str | None = None,
    resolver: Callable[..., Any] | None = None,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> WebhookResult:
    """POST a signed payload to a validated destination."""
    schemes = frozenset({"https", "http"}) if target.allow_insecure_http else frozenset({"https"})
    try:
        resolved = await resolve_and_validate(
            str(target.url),
            schemes=schemes,
            allow_private=not settings.webhook_block_private,
            resolver=resolver,
        )
    except UnsafeURL as exc:
        return WebhookResult(False, error=str(exc)[:500])
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    stamp = timestamp or str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-ToneWatch-Timestamp": stamp,
        "X-ToneWatch-Signature": signature(target.secret, stamp, body),
    }
    attachment = (
        _recording_attachment(local_attachment_path, settings) if target.include_audio else None
    )
    if target.include_audio and local_attachment_path and attachment is None:
        return WebhookResult(False, error="attachment is missing, outside the root, or too large")
    current: ResolvedURL = resolved
    client: httpx.AsyncClient | None = None
    try:
        for hop in range(6):
            client = client_factory(
                transport=PinnedIPTransport(current),
                follow_redirects=False,
                timeout=10.0,
                trust_env=False,
            )
            url = current.original.copy_with(host=str(current.address))
            request_headers = dict(headers)
            host = current.host
            if current.original.port not in (None, 80, 443):
                host = f"{host}:{current.original.port}"
            request_headers["Host"] = host
            if attachment is None:
                request = client.build_request("POST", url, headers=request_headers, content=body)
            else:
                request = client.build_request(
                    "POST",
                    url,
                    headers=request_headers,
                    data={"payload": body.decode()},
                    files={"audio": attachment},
                )
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not settings.webhook_allow_redirects or not location or hop == 5:
                        return WebhookResult(False, response.status_code, "redirect refused")
                    next_url = httpx.URL(urljoin(str(current.original), location))
                    current = await resolve_and_validate(
                        next_url,
                        schemes=schemes,
                        allow_private=not settings.webhook_block_private,
                        resolver=resolver,
                    )
                    continue
                response_body = await _read_limited(response)
                if 200 <= response.status_code < 300:
                    return WebhookResult(True, response.status_code)
                return WebhookResult(
                    False,
                    response.status_code,
                    f"webhook returned HTTP {response.status_code}: "
                    f"{_safe_error(response_body.decode(errors='replace')[:400], target.secret)}",
                )
            finally:
                await response.aclose()
                await client.aclose()
                client = None
        return WebhookResult(False, error="redirect limit exceeded")
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        return WebhookResult(False, error=_safe_error(str(exc), target.secret))
    finally:
        if client is not None:
            await client.aclose()
