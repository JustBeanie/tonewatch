"""Home Assistant MQTT discovery publication and cleanup."""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tonewatch.config.models import AppConfig


class DiscoveryPublisher(Protocol):
    """Minimum publisher surface needed by discovery."""

    @property
    def availability_topic(self) -> str:
        """Return the availability topic."""
        ...

    def publish(self, topic: str, payload: object, *, retain: bool = False) -> Awaitable[None]:
        """Publish a retained discovery payload."""


class HADiscovery:
    """Publish stable per-instance discovery entities."""

    def __init__(
        self, publisher: DiscoveryPublisher, instance_id: str, enabled: bool = True
    ) -> None:
        self.publisher, self.instance_id, self.enabled = publisher, instance_id, enabled
        self._topics: set[str] = set()

    def _topic(self, component: str, key: str) -> str:
        return f"homeassistant/{component}/tonewatch_{self.instance_id}_{key}/config"

    async def publish(self, config: AppConfig) -> None:
        """Publish all current entities and clear entities removed since the last config."""
        if not self.enabled:
            return
        topics: dict[str, dict[str, object]] = {}
        device = {"identifiers": [f"tonewatch_{self.instance_id}"], "name": "ToneWatch"}
        availability = {"topic": self.publisher.availability_topic}
        for toneset in config.tone_sets:
            key = f"event_{toneset.id}"
            topics[self._topic("event", key)] = {
                "name": toneset.name,
                "unique_id": f"{self.instance_id}_{key}",
                "event_types": ["pre_alert", "recording_ready"],
                "state_topic": f"tonewatch/{self.instance_id}/call",
                "event_topic": f"tonewatch/{self.instance_id}/call",
                "availability": availability,
                "device": device,
            }
        if any(
            target.enabled and "tone_discovered" in getattr(target, "events", ())
            for target in config.alert_targets
        ):
            key = "event_tone_discovered"
            topics[self._topic("event", key)] = {
                "name": "Tone discovered",
                "unique_id": f"{self.instance_id}_{key}",
                "event_types": ["tone_discovered"],
                "state_topic": f"tonewatch/{self.instance_id}/discovered",
                "event_topic": f"tonewatch/{self.instance_id}/discovered",
                "availability": availability,
                "device": device,
            }
        topics[self._topic("sensor", "last_call")] = {
            "name": "Last call",
            "unique_id": f"{self.instance_id}_last_call",
            "state_topic": f"tonewatch/{self.instance_id}/call",
            "value_template": "{{ value_json.call_id }}",
            "availability": availability,
            "device": device,
        }
        topics[self._topic("binary_sensor", "call_active")] = {
            "name": "Call active",
            "unique_id": f"{self.instance_id}_call_active",
            "state_topic": f"tonewatch/{self.instance_id}/call",
            "value_template": "{{ 'ON' if value_json.phase != 'closed' else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
            "device": device,
        }
        for source in config.sources:
            key = f"{source.id}_feed_healthy"
            topics[self._topic("binary_sensor", key)] = {
                "name": f"{source.name} feed healthy",
                "unique_id": f"{self.instance_id}_{key}",
                "state_topic": f"tonewatch/{self.instance_id}/health/{source.id}",
                "payload_on": "online",
                "payload_off": "offline",
                "availability": availability,
                "device": device,
            }
            if source.squelch.mode != "off":
                key = f"{source.id}_activity"
                topics[self._topic("binary_sensor", key)] = {
                    "name": f"{source.name} activity",
                    "unique_id": f"{self.instance_id}_{key}",
                    "state_topic": f"tonewatch/{self.instance_id}/activity/{source.id}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "sound",
                    "availability": availability,
                    "device": device,
                }
        for topic in self._topics - topics.keys():
            await self.publisher.publish(topic, "", retain=True)
        for topic, payload in topics.items():
            await self.publisher.publish(
                topic, json.dumps(payload, separators=(",", ":")), retain=True
            )
        self._topics = set(topics)
