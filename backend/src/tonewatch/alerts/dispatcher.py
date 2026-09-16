"""Concurrent alert dispatch with dedupe, retries, and durable attempt records."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from tonewatch.admin.health import OutputHealth, bounded_error
from tonewatch.alerts.ha_discovery import HADiscovery
from tonewatch.alerts.meshtastic import MeshtasticSender
from tonewatch.alerts.mqtt import MqttPublisher
from tonewatch.alerts.script import run_script
from tonewatch.alerts.webhook import WebhookResult, send_webhook
from tonewatch.config.models import (
    AlertTarget,
    AppConfig,
    MeshtasticTarget,
    MqttTarget,
    ScriptTarget,
    WebhookTarget,
)
from tonewatch.events import (
    CallClosed,
    EventBus,
    FeedHealthChanged,
    RecordingReady,
    RecordingStored,
    SquelchChanged,
    Subscription,
    ToneDetected,
    ToneDiscovered,
)
from tonewatch.storage.models import AlertAttempt, Call

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
        self._coalescing: dict[tuple[UUID, str], asyncio.Task[None]] = {}
        self._mesh_sent: set[tuple[UUID, str]] = set()
        self._seen: set[tuple[UUID, str, str]] = set()
        self._calls: dict[UUID, dict[str, Any]] = defaultdict(
            lambda: {"tone_sets": [], "test": False, "source_id": "", "recording_path": None}
        )
        self._mqtt: dict[str, MqttPublisher] = {}
        self._meshtastic: dict[str, MeshtasticSender] = {}
        self._discovery: dict[str, HADiscovery] = {}
        self.output_health: dict[str, OutputHealth] = defaultdict(OutputHealth)
        self._retrying: set[int] = set()

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
        await self._cancel_coalescing()
        for publisher in tuple(self._mqtt.values()):
            await publisher.stop()
        self._mqtt.clear()
        self._meshtastic.clear()
        self._discovery.clear()

    async def reload(self, config: AppConfig) -> None:
        """Apply target changes without discarding the call dedupe state."""
        await self._cancel_coalescing()
        self.config = config
        if self.task is not None:
            await self._configure_targets(config)

    async def _cancel_coalescing(self) -> None:
        pending = tuple(self._coalescing.values())
        self._coalescing.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _configure_targets(self, config: AppConfig) -> None:
        mqtt_enabled = getattr(self.settings, "mqtt_mode", "supervisor") != "off"
        targets = {
            target.id: target
            for target in config.alert_targets
            if target.enabled and (mqtt_enabled or not isinstance(target, MqttTarget))
        }
        self._meshtastic = {
            target.id: MeshtasticSender(
                target,
                next(
                    (
                        candidate
                        for candidate in config.alert_targets
                        if isinstance(candidate, MqttTarget)
                        and candidate.id == target.mqtt_target_id
                    ),
                    None,
                ),
            )
            for target in targets.values()
            if isinstance(target, MeshtasticTarget)
        }
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
                if target.ha_discovery:
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
            if isinstance(event, SquelchChanged):
                await asyncio.gather(
                    *(
                        publisher.publish_activity(event.source_id, event.open)
                        for publisher in self._mqtt.values()
                    ),
                    return_exceptions=True,
                )
                continue
            if isinstance(event, ToneDiscovered):
                await self._handle_discovered(event)
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

    async def _handle_discovered(self, event: ToneDiscovered) -> None:
        """Dispatch a discovery event only to targets that opt in."""
        relative_clip = (
            f"/api/discovered-tones/{event.cluster_id}/clip"
            if event.cluster_id is not None
            else None
        )
        public_base = getattr(self.settings, "public_base_url", None)
        clip_url = (
            f"{str(public_base).rstrip('/')}{relative_clip}"
            if public_base and relative_clip
            else relative_clip
        )
        payload: dict[str, object] = {
            "event": "tone_discovered",
            "frequencies": list(event.candidate.frequencies),
            "durations": list(event.candidate.durations),
            "count": event.count,
            "source": event.source_id,
            "source_id": event.source_id,
            "clip_url": clip_url,
        }
        if not public_base:
            payload["recording_path_relative"] = True
        await asyncio.gather(
            *(
                self._dispatch_discovered(target, payload)
                for target in self.config.alert_targets
                if target.enabled and "tone_discovered" in getattr(target, "events", ())
            ),
            return_exceptions=True,
        )

    async def _dispatch_discovered(self, target: AlertTarget, payload: dict[str, object]) -> None:
        if isinstance(target, MqttTarget):
            await self._mqtt[target.id].publish_discovered(payload)
        elif isinstance(target, WebhookTarget):
            await send_webhook(target, payload, self.settings)

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
            state.update(
                source_id=event.source_id,
                test=state["test"] or test,
                detected_at=state.get("detected_at") or event.detected_at,
                agency=self._agency_for_tone_sets(state["tone_sets"]),
            )
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
            recording_id=event.recording_id if isinstance(event, RecordingStored) else None,
            public_base_url=getattr(self.settings, "public_base_url", None),
            tone_set_names=self._tone_set_names(state["tone_sets"]),
        )
        await self._fan_out(call_id, phase, target_ids, payload, state)
        if isinstance(event, CallClosed):
            self._mesh_sent = {key for key in self._mesh_sent if key[0] != call_id}
            if state.get("recording_path") is None:
                self._calls.pop(call_id, None)
            else:
                state["closed"] = True
        elif isinstance(event, RecordingStored) and state.get("closed"):
            self._calls.pop(call_id, None)

    async def _fan_out(
        self,
        call_id: UUID,
        phase: str,
        target_ids: set[str],
        payload: dict[str, object],
        state: dict[str, Any],
    ) -> None:
        local_audio_path = (
            state.get("recording_path") if isinstance(state.get("recording_path"), str) else None
        )
        immediate: list[Awaitable[None]] = []
        for target_id in target_ids:
            target = next(
                (item for item in self.config.alert_targets if item.id == target_id), None
            )
            if (
                isinstance(target, MeshtasticTarget)
                and phase == "pre_alert"
                and phase in target.phases
            ):
                key = (call_id, target_id)
                if key not in self._mesh_sent and key not in self._coalescing:
                    task = asyncio.create_task(
                        self._coalesce_and_dispatch(call_id, target_id),
                        name="tonewatch-meshtastic-coalesce",
                    )
                    self._coalescing[key] = task

                    def finished_coalescing(
                        _done: asyncio.Task[None], key: tuple[UUID, str] = key
                    ) -> None:
                        self._coalescing.pop(key, None)

                    task.add_done_callback(finished_coalescing)
                elif key in self._mesh_sent:
                    immediate.append(self._dispatch(target_id, phase, call_id, payload, force=True))
            else:
                immediate.append(
                    self._dispatch(
                        target_id, phase, call_id, payload, local_audio_path=local_audio_path
                    )
                )
        await asyncio.gather(*immediate, return_exceptions=True)

    async def _coalesce_and_dispatch(self, call_id: UUID, target_id: str) -> None:
        target = next((item for item in self.config.alert_targets if item.id == target_id), None)
        if not isinstance(target, MeshtasticTarget):
            return
        await self.sleep(target.coalesce_s)
        target = next((item for item in self.config.alert_targets if item.id == target_id), None)
        if not isinstance(target, MeshtasticTarget) or not target.enabled:
            return
        state = self._calls[call_id]
        state["agency"] = self._agency_for_tone_sets(state["tone_sets"])
        payload = self._payload(
            call_id,
            "pre_alert",
            state,
            bool(state.get("test")),
            state.get("detected_at"),
            public_base_url=getattr(self.settings, "public_base_url", None),
            tone_set_names=self._tone_set_names(state["tone_sets"]),
        )
        self._mesh_sent.add((call_id, target_id))
        await self._dispatch(target_id, "pre_alert", call_id, payload, force=True)

    def _tone_set_names(self, tone_set_ids: list[str]) -> list[str]:
        names = {item.id: item.name for item in self.config.tone_sets}
        return [names.get(item, item) for item in tone_set_ids]

    def _agency_for_tone_sets(self, tone_set_ids: list[str]) -> dict[str, object] | None:
        agencies = {item.id: item for item in self.config.agencies}
        found = []
        for tone_set_id in tone_set_ids:
            tone_set = next(
                (item for item in self.config.tone_sets if item.id == tone_set_id), None
            )
            agency = (
                agencies.get(tone_set.agency_id)
                if tone_set is not None and tone_set.agency_id is not None
                else None
            )
            if agency is not None and agency not in found:
                found.append(agency)
        if not found:
            return None
        return {
            "id": "/".join(item.id for item in found),
            "name": "/".join(item.name for item in found),
            "short_name": "/".join(item.short_name for item in found),
            "kind": "/".join(item.kind for item in found),
            "lat": found[0].location.lat,
            "lon": found[0].location.lon,
        }

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
        recording_id: int | None = None,
        public_base_url: str | None = None,
        tone_set_names: list[str] | None = None,
    ) -> dict[str, object]:
        if recording_id is not None:
            relative_url = f"/api/recordings/{recording_id}"
            recording_url = (
                f"{public_base_url.rstrip('/')}{relative_url}" if public_base_url else relative_url
            )
        payload: dict[str, object] = {
            "call_id": str(call_id),
            "tone_sets": list(state["tone_sets"]),
            "phase": phase,
            "detected_at": detected_at.isoformat() if detected_at else None,
            "recording_url": recording_url,
            "source_id": state.get("source_id", ""),
            "test": bool(state.get("test") or test),
            "agency": state.get("agency"),
        }
        if public_base_url is None:
            payload["recording_path_relative"] = True
        payload["toneset"] = state["tone_sets"][0] if state["tone_sets"] else ""
        payload["tone_set_names"] = tone_set_names or list(state["tone_sets"])
        payload["agency"] = state.get("agency")
        return payload

    async def _dispatch(
        self,
        target_id: str,
        phase: str,
        call_id: UUID,
        payload: dict[str, object],
        *,
        local_audio_path: str | None = None,
        force: bool = False,
    ) -> None:
        key = (call_id, target_id, phase)
        if key in self._seen and not force:
            return
        if not force:
            self._seen.add(key)
        target = next((item for item in self.config.alert_targets if item.id == target_id), None)
        if target is None or not target.enabled:
            return
        phases = target.phases if isinstance(target, MeshtasticTarget) else target.events
        if phase not in phases:
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
            self.output_health[target_id].record(
                ok, datetime.now().astimezone(), getattr(outcome, "error", None)
            )
            await self._record(call_id, target_id, phase, attempt_no, ok, outcome)
            if ok:
                return
            if getattr(outcome, "error", None) == "rate_limited":
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
        if isinstance(target, MeshtasticTarget):
            return await self._meshtastic[target.id].send(payload)
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

    async def test_target(self, target_id: str) -> dict[str, object]:
        """Send exactly one synthetic TEST attempt without creating a call or attempt row."""
        target = next((item for item in self.config.alert_targets if item.id == target_id), None)
        if target is None:
            raise ValueError("alert target not found")
        payload: dict[str, object] = {
            "call_id": "test",
            "tone_sets": ["TEST"],
            "toneset": "TEST",
            "phase": "pre_alert",
            "detected_at": datetime.now().astimezone().isoformat(),
            "recording_url": None,
            "source_id": "test",
            "test": True,
        }
        try:
            outcome = await asyncio.wait_for(
                self._send(target, payload), getattr(target, "timeout_s", self.timeout_s)
            )
        except TimeoutError:
            return {"ok": False, "error": "target timeout"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}
        return {"ok": bool(getattr(outcome, "ok", False)), "error": getattr(outcome, "error", None)}

    async def _record(
        self,
        call_id: UUID,
        target_id: str,
        phase: str,
        attempt_no: int,
        ok: bool,
        result: Any,
        *,
        retry: bool = False,
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
                        retry=retry,
                    )
                )
                await session.commit()
        except Exception:
            self.logger.exception(
                "alert attempt persistence failed", extra={"call_id": str(call_id)}
            )

    async def retry_attempt(self, attempt_id: int) -> tuple[int, dict[str, object]]:
        """Retry one failed delivery exactly once through its configured sender."""
        if attempt_id in self._retrying:
            return 429, {"ok": False, "error": "retry_in_flight"}
        self._retrying.add(attempt_id)
        try:
            if self.session_factory is None:
                return 404, {"ok": False, "error": "attempt not found"}
            async with self.session_factory() as session:
                attempt = await session.get(AlertAttempt, attempt_id)
                if attempt is None:
                    return 404, {"ok": False, "error": "attempt not found"}
                if attempt.ok:
                    return 409, {"ok": False, "error": "attempt already succeeded"}
                target = next(
                    (item for item in self.config.alert_targets if item.id == attempt.target_id),
                    None,
                )
                if target is None or not target.enabled:
                    return 409, {"ok": False, "error": "target unavailable"}
                call = await session.get(Call, attempt.call_id)
                if call is None:
                    return 409, {"ok": False, "error": "call unavailable"}
                payload = self._calls.get(attempt.call_id, {}).copy()
                payload.update(
                    {
                        "call_id": str(attempt.call_id),
                        "phase": attempt.phase,
                        "retry": True,
                        "source_id": call.source_id,
                        "test": False,
                    }
                )
            try:
                outcome = await asyncio.wait_for(
                    self._send(target, payload), getattr(target, "timeout_s", self.timeout_s)
                )
            except TimeoutError:
                outcome = WebhookResult(False, error="target timeout")
            except Exception as exc:
                outcome = WebhookResult(False, error=bounded_error(exc))
            ok = bool(getattr(outcome, "ok", False))
            self.output_health[target.id].record(
                ok, datetime.now().astimezone(), getattr(outcome, "error", None)
            )
            result = WebhookResult(
                ok,
                status_code=getattr(outcome, "status_code", None),
                error=getattr(outcome, "error", None),
            )
            await self._record(
                attempt.call_id,
                target.id,
                attempt.phase,
                attempt.attempt_no + 1,
                ok,
                result,
                retry=True,
            )
            return 200, {"ok": ok, "error": getattr(outcome, "error", None), "target_id": target.id}
        finally:
            self._retrying.discard(attempt_id)
