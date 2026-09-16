"""Meshtastic MQTT JSON downlink sender."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
from collections import deque
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiomqtt

from tonewatch.config.models import MeshtasticTarget, MqttTarget

_URL = re.compile(
    r"(?:\b[a-z][a-z0-9+.-]*://|\bwww\.)\S+"
    r"|(?:\b(?:[a-z0-9-]+\.)+[a-z]{2,})(?::\d+)?(?:/\S*)?"
    r"|\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/\S*)?"
    r"|\[(?:[0-9a-f:]+)\](?::\d+)?(?:/\S*)?",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class MeshtasticResult:
    """Result compatible with the dispatcher's alert result handling."""

    def __init__(self, ok: bool, error: str | None = None) -> None:
        self.ok, self.error, self.status_code = ok, error, 0 if ok else None


def sanitize(value: object) -> str:
    """Remove controls, URLs, and excess whitespace from an untrusted value."""
    if value is None:
        return ""
    return " ".join(_URL.sub("", _CONTROL.sub(" ", str(value))).split())


def _value_text(value: object, *, key: str = "") -> str:
    if isinstance(value, dict):
        selected = value.get(key) if key else None
        return sanitize(selected if selected is not None else value.get("name", ""))
    if isinstance(value, list):
        return ",".join(_value_text(item) for item in value)
    return sanitize(value)


def _timezone(name: str) -> tzinfo:
    return UTC if name == "UTC" else ZoneInfo(name)


def truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate at a code-point boundary, adding an ellipsis when it fits."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    ellipsis = "…"
    budget = max_bytes - len(ellipsis.encode())
    if budget < 0:
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[:budget].decode("utf-8", errors="ignore")
    return prefix + ellipsis


def render_untruncated(target: MeshtasticTarget, payload: dict[str, object]) -> str:
    """Render and sanitize the configured notification template without a byte cap."""
    tonesets = payload.get("tone_sets", [])
    names = payload.get("tone_set_names", tonesets)
    joined = _value_text(names)
    fallback = _value_text(payload.get("tone_set_name", payload.get("toneset", ""))) or joined
    when = payload.get("detected_at")
    try:
        zone_name = target.timezone or os.environ.get("TZ") or "UTC"
        local_time = (
            datetime.fromisoformat(str(when)).astimezone(_timezone(zone_name)).strftime("%H:%M")
        )
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        try:
            zone_name = target.timezone or os.environ.get("TZ") or "UTC"
            local_time = datetime.now(_timezone(zone_name)).strftime("%H:%M")
        except ZoneInfoNotFoundError:
            local_time = datetime.now(UTC).strftime("%H:%M")
    agency = payload.get("agency")
    agency_short = (
        agency.get("short_name") if isinstance(agency, dict) else payload.get("agency_short")
    )
    agency_name = agency.get("name") if isinstance(agency, dict) else agency
    values = {
        "agency_short": _value_text(agency_short) or fallback,
        "agency": _value_text(agency_name) or fallback,
        "toneset": fallback,
        "tonesets": joined or fallback,
        "time": local_time,
        "source": sanitize(payload.get("source_id", payload.get("source", ""))),
        "call_id_short": sanitize(str(payload.get("call_id", ""))[:8]),
    }
    rendered = target.template.format(**values)
    if payload.get("test"):
        rendered = f"TEST {rendered}"
    return sanitize(rendered)


def render_message(target: MeshtasticTarget, payload: dict[str, object]) -> str:
    """Render, sanitize, and truncate the configured notification template."""
    return truncate_utf8(render_untruncated(target, payload), target.max_bytes)


class MeshtasticSender:
    """Publish one target's JSON downlink with local rate limiting."""

    def __init__(self, target: MeshtasticTarget, broker: MqttTarget | None = None) -> None:
        self.target = target
        self.broker = broker
        self._sent: deque[float] = deque()
        self._last_sent = 0.0

    def topic(self) -> str:
        return self.target.root_topic.rstrip("/") + "/2/json/mqtt/"

    def _allowed(self, now: float) -> bool:
        while self._sent and self._sent[0] <= now - 3600:
            self._sent.popleft()
        return (
            now - self._last_sent >= self.target.min_interval_s
            and len(self._sent) < self.target.max_per_hour
        )

    def rate_limited(self) -> bool:
        return not self._allowed(time.monotonic())

    async def send(self, payload: dict[str, object]) -> MeshtasticResult:
        """Publish at QoS 1 without retaining the message."""
        now = time.monotonic()
        if not self._allowed(now):
            return MeshtasticResult(False, "rate_limited")
        broker = self.broker
        host = self.target.host if broker is None else broker.hostname
        port = self.target.port if broker is None else broker.port
        tls = self.target.tls if broker is None else broker.tls
        username = self.target.username if broker is None else broker.username
        password = self.target.password if broker is None else broker.password
        envelope: dict[str, object] = {
            "from": self.target.gateway_number,
            "to": self.target.destination_number,
            "channel": self.target.channel_index,
            "type": "sendtext",
            "payload": render_message(self.target, payload),
        }
        try:
            async with aiomqtt.Client(
                hostname=host or "localhost",
                port=port,
                username=username,
                password=password,
                tls_context=None if not tls else ssl.create_default_context(),
            ) as client:
                await client.publish(self.topic(), json.dumps(envelope), qos=1, retain=False)
        except Exception as exc:
            return MeshtasticResult(False, str(exc)[:500])
        self._last_sent = now
        self._sent.append(now)
        return MeshtasticResult(True)
