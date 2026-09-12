"""Concurrent alert dispatch with dedupe, retries, and durable attempt records."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tonewatch.alerts.ha_discovery import HADiscovery
from tonewatch.alerts.mqtt import MqttPublisher
from tonewatch.alerts.script import run_script
from tonewatch.alerts.webhook import WebhookResult, send_webhook
from tonewatch.config.models import AlertTarget, AppConfig, MqttTarget, ScriptTarget, WebhookTarget
from tonewatch.events import (
    CallClosed,
    EventBus,
    FeedHealthChanged,
    RecordingReady,
    RecordingStored,
    Subscription,
    ToneDetected,
)
from tonewatch.storage.models import AlertAttempt

if TYPE_CHECKING:
    from uuid import UUID

Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]
LOGGER = logging.getLogger("tonewatch.alerts")


class AlertDispatcher:
    """Consume domain events and fan them out to configured target instances."""

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        session_factory: Any = None,
        *,
        settings: Any = None,
        instance_id: str = "default",
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.config, self.bus, self.session_factory = config, bus, session_factory
        self.settings, self.instance_id = settings, instance_id
        self.logger = LOGGER
        self.sleep, self.jitter, self.timeout_s = sleep, jitter or self._jitter, timeout_s
        self.subscription: Subscription | None = None
        self.task: asyncio.Task[None] | None = None
        self._deliveries: set[asyncio.Task[None]] = set()
        self._event_chains: dict[UUID, asyncio.Task[None]] = {}
        self._seen: set[tuple[UUID, str, str]] = set()
        self._calls: dict[UUID, dict[str, Any]] = defaultdict(
            lambda: {"tone_sets": [], "test": False, "source_id": "", "recording_path": None}
        )
        self._mqtt: dict[str, MqttPublisher] = {}
        self._discovery: dict[str, HADiscovery] = {}

    @staticmethod
    def _jitter(delay: float) -> float:
        """Apply bounded jitter without changing the exponential backoff schedule."""
        return secrets.SystemRandom().uniform(delay * 0.9, delay * 1.1)

    async def start(self) -> None:
        """Subscribe to all alert-relevant events and start target services."""
        if self.task is not None:
            return
        self.subscription = self.bus.subscribe(maxsize=1000)
        await self._configure_targets(self.config)
        self.task = asyncio.create_task(self._consume(), name="tonewatch-alert-dispatcher")

    async def stop(self) -> None:
        """Stop target services and await in-flight deliveries."""
        if self.subscription is not None:
            self.bus.unsubscribe(self.subscription)
            self.subscription = None
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        deliveries = tuple(self._deliveries)
        if deliveries:
            await asyncio.gather(*deliveries, return_exceptions=True)
        for publisher in tuple(self._mqtt.values()):
            await publisher.stop()
        self._mqtt.clear()
        self._discovery.clear()

    async def reload(self, config: AppConfig) -> None:
        """Apply target changes without discarding the call dedupe state."""
        self.config = config
        if self.task is not None:
            await self._configure_targets(config)

    async def _configure_targets(self, config: AppConfig) -> None:
        targets = {target.id: target for target in config.alert_targets if target.enabled}
        for target_id in set(self._mqtt) - set(targets):
            await self._mqtt.pop(target_id).stop()
        for target in targets.values():
            if isinstance(target, MqttTarget) and target.id not in self._mqtt:
                publisher = MqttPublisher(
                    target,
                    self.instance_id,
                    addon_mode=bool(getattr(self.settings, "addon_mode", False)),
                )
                self._mqtt[target.id] = publisher
                await publisher.start()
                self._discovery[target.id] = HADiscovery(
                    publisher,
                    self.instance_id,
                    enabled=not bool(getattr(self.settings, "ha_integration_enabled", False)),
                )
            elif isinstance(target, MqttTarget) and target.id in self._mqtt:
                await self._mqtt[target.id].start()
        for discovery in self._discovery.values():
            await discovery.publish(config)

    async def _consume(self) -> None:
        if self.subscription is None:
            return
        async for event in self.subscription:
            if isinstance(event, FeedHealthChanged):
                await self._health(event)
                continue
            if not isinstance(event, (ToneDetected, RecordingReady, RecordingStored, CallClosed)):
                continue
            previous = self._event_chains.get(event.call_id)

            async def process(
                previous: asyncio.Task[None] | None = previous,
                event: ToneDetected | RecordingReady | RecordingStored | CallClosed = event,
            ) -> None:
                if previous is not None:
                    await asyncio.gather(previous, return_exceptions=True)
                await self.handle(event)

            task = asyncio.create_task(process(), name="tonewatch-alert-event")
            self._deliveries.add(task)

            def finished(done: asyncio.Task[None], call_id: UUID = event.call_id) -> None:
                self._deliveries.discard(done)
                if self._event_chains.get(call_id) is done:
                    self._event_chains.pop(call_id, None)

            self._event_chains[event.call_id] = task
            task.add_done_callback(finished)

    async def _health(self, event: FeedHealthChanged) -> None:
        await asyncio.gather(
            *(
                publisher.publish_health(event.source_id, event.healthy)
                for publisher in self._mqtt.values()
            ),
            return_exceptions=True,
        )

    async def handle(
        self, event: ToneDetected | RecordingReady | RecordingStored | CallClosed
    ) -> None:
        """Process one domain event, primarily useful for deterministic tests."""
        phase: str
        call_id: UUID
        test = False
        recording_url: str | None = None
        if isinstance(event, ToneDetected):
            call_id, phase, test = event.call_id, "pre_alert", event.test
            state = self._calls[call_id]
            if event.toneset_id not in state["tone_sets"]:
                state["tone_sets"].append(event.toneset_id)
            state.update(source_id=event.source_id, test=state["test"] or test)
            detected_at = event.detected_at
        elif isinstance(event, RecordingReady):
            call_id = event.call_id
            state = self._calls[call_id]
            state["recording_path"] = event.path
            return
        elif isinstance(event, RecordingStored):
            call_id, phase = event.call_id, "recording_ready"
            state = self._calls[call_id]
            state.update(source_id=event.source_id, test=state["test"] or event.test)
            test, detected_at = bool(state["test"]), None
            recording_url = f"/api/recordings/{event.recording_id}"
        else:
            call_id, phase, test = event.call_id, "closed", event.test
            state = self._calls[call_id]
            state["test"] = state["test"] or test
            detected_at = None
        target_ids = self._target_ids(state["tone_sets"])
        payload = self._payload(
            call_id,
            phase,
            state,
            test,
            detected_at,
            recording_url=recording_url,
        )
        await asyncio.gather(
            *(
                self._dispatch(
                    target_id,
                    phase,
                    call_id,
                    payload,
                    local_audio_path=(
                        state.get("recording_path")
                        if isinstance(state.get("recording_path"), str)
                        else None
                    ),
                )
                for target_id in target_ids
            ),
            return_exceptions=True,
        )

    def _target_ids(self, tonesets: list[str]) -> set[str]:
        return {
            target_id
            for toneset in self.config.tone_sets
            if toneset.id in tonesets
            for target_id in toneset.alert_targets
        }

    @staticmethod
    def _payload(
        call_id: UUID,
        phase: str,
        state: dict[str, Any],
        test: bool,
        detected_at: datetime | None,
        *,
        recording_url: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "call_id": str(call_id),
            "tone_sets": list(state["tone_sets"]),
            "phase": phase,
            "detected_at": detected_at.isoformat() if detected_at else None,
            "recording_url": recording_url,
            "source_id": state.get("source_id", ""),
            "test": bool(state.get("test") or test),
        }
        payload["toneset"] = state["tone_sets"][0] if state["tone_sets"] else ""
        return payload

    async def _dispatch(
        self,
        target_id: str,
        phase: str,
        call_id: UUID,
        payload: dict[str, object],
        *,
        local_audio_path: str | None = None,
    ) -> None:
        key = (call_id, target_id, phase)
        if key in self._seen:
            return
        self._seen.add(key)
        target = next((item for item in self.config.alert_targets if item.id == target_id), None)
        if target is None or not target.enabled:
            return
        for attempt_no in range(1, 6):
            try:
                outcome = await asyncio.wait_for(
                    self._send(target, payload, local_audio_path=local_audio_path),
                    self.timeout_s,
                )
            except TimeoutError:
                outcome = WebhookResult(False, error="target timeout")
            except Exception as exc:
                outcome = WebhookResult(False, error=str(exc)[:500])
            ok = bool(getattr(outcome, "ok", False))
            await self._record(call_id, target_id, phase, attempt_no, ok, outcome)
            if ok:
                return
            if attempt_no < 5:
                await self.sleep(self.jitter(float(2 ** (attempt_no - 1))))

    async def _send(
        self,
        target: AlertTarget,
        payload: dict[str, object],
        *,
        local_audio_path: str | None = None,
    ) -> Any:
        if isinstance(target, MqttTarget):
            await self._mqtt[target.id].publish_call(payload)
            return WebhookResult(True, status_code=0)
        if isinstance(target, WebhookTarget):
            return await send_webhook(
                target,
                payload,
                self.settings,
                local_attachment_path=local_audio_path,
            )
        if isinstance(target, ScriptTarget):
            script_payload = dict(payload)
            if local_audio_path is not None:
                script_payload["recording_path"] = local_audio_path
            return await run_script(
                target,
                script_payload,
                allow_script_targets=bool(getattr(self.settings, "allow_script_targets", False)),
                allowlist_dirs=list(getattr(self.settings, "script_allowlist_dirs", [])),
            )
        return WebhookResult(False, error="unsupported target")

    async def _record(
        self,
        call_id: UUID,
        target_id: str,
        phase: str,
        attempt_no: int,
        ok: bool,
        result: Any,
    ) -> None:
        if self.session_factory is None:
            return
        error = getattr(result, "error", None)
        if error is not None:
            error = str(error)[:500]
        try:
            async with self.session_factory() as session:
                session.add(
                    AlertAttempt(
                        call_id=call_id,
                        target_id=target_id,
                        phase=phase,
                        attempt_no=attempt_no,
                        ok=ok,
                        status_code=getattr(result, "status_code", None),
                        error=error,
                        created_at=datetime.now().astimezone(),
                    )
                )
                await session.commit()
        except Exception:
            self.logger.exception(
                "alert attempt persistence failed", extra={"call_id": str(call_id)}
            )
