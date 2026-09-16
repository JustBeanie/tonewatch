"""Clock-injected operational alert state machine."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tonewatch.events import FeedHealthChanged, SquelchHealthChanged

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from tonewatch.config.models import AdminAlertsConfig

LOGGER = logging.getLogger("tonewatch.admin.alerts")
HOUR_S = 3600.0


@dataclass
class _Latch:
    true_since: float | None = None
    latched: bool = False
    last_notice: float | None = None
    reminders: deque[float] = field(default_factory=deque)
    dropped: int = 0


class AdminAlertEngine:
    """Evaluate health snapshots and deliver each condition on its edge."""

    def __init__(
        self,
        config: AdminAlertsConfig,
        dispatcher: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create an engine with monotonic and wall-clock dependencies."""
        self.config = config
        self.dispatcher = dispatcher
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self.latches: dict[str, _Latch] = {}
        self.feed_healthy: dict[str, bool] = {}
        self.squelch_stuck: dict[str, bool] = {}
        self._hourly: deque[float] = deque()
        self._inflight: set[str] = set()
        self.subscription: Any = None
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start consuming transition events."""
        if self.task is not None:
            return
        self.subscription = self.dispatcher.bus.subscribe()
        self.task = asyncio.create_task(self._consume(), name="tonewatch-admin-alert-events")

    async def stop(self) -> None:
        """Cancel event consumption and forget active latches."""
        if self.subscription is not None:
            self.dispatcher.bus.unsubscribe(self.subscription)
            self.subscription = None
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.clear()

    async def reload(self, config: AdminAlertsConfig) -> None:
        """Apply configuration and clear state when disabled."""
        self.config = config
        if not config.enabled:
            self.clear()

    def clear(self) -> None:
        """Clear latches and rate-limit history."""
        self.latches.clear()
        self._hourly.clear()
        self._inflight.clear()

    async def _consume(self) -> None:
        if self.subscription is None:
            return
        async for event in self.subscription:
            if isinstance(event, FeedHealthChanged):
                self.feed_healthy[event.source_id] = event.healthy
            elif isinstance(event, SquelchHealthChanged):
                self.squelch_stuck[event.source_id] = event.stuck_open

    def _notice_allowed(self, state: _Latch, now: float) -> bool:
        if state.last_notice is None or now - state.last_notice >= self.config.min_interval_s:
            while self._hourly and now - self._hourly[0] >= HOUR_S:
                self._hourly.popleft()
            return len(self._hourly) < self.config.max_per_hour
        return False

    async def evaluate(self, snapshot: Mapping[str, Any]) -> None:
        """Evaluate a health snapshot; filesystem work belongs to the caller."""
        if not self.config.enabled:
            return
        now = self.clock()
        conditions: dict[str, tuple[bool, float, str, dict[str, object]]] = {}
        sources = snapshot.get("sources", {})
        source_ids = set(sources) | set(snapshot.get("feed_healthy", {}))
        for source_id in source_ids:
            metric = sources.get(source_id)
            healthy = self.feed_healthy.get(source_id, True)
            healthy = bool(snapshot.get("feed_healthy", {}).get(source_id, healthy))
            history = getattr(metric, "feed_health_history", ())
            if history:
                healthy = bool(history[-1].get("healthy", healthy))
            factor_value = getattr(getattr(metric, "factor", None), "value", metric)
            factor = factor_value if isinstance(factor_value, (int, float)) else None
            conditions[f"feed_unhealthy:{source_id}"] = (
                not healthy,
                self.config.feed_unhealthy_min * 60,
                f"Feed {source_id} has been unhealthy",
                {"source_id": source_id},
            )
            conditions[f"squelch_stuck_open:{source_id}"] = (
                self.config.squelch_stuck_open and self.squelch_stuck.get(source_id, False),
                0,
                f"Squelch on {source_id} is stuck open",
                {"source_id": source_id},
            )
            conditions[f"realtime_factor:{source_id}"] = (
                factor is not None and factor < self.config.realtime_factor_min,
                self.config.realtime_factor_min_s,
                f"DSP realtime factor on {source_id} is below threshold",
                {"source_id": source_id, "realtime_factor": factor},
            )
        disk = snapshot.get("disk", {})
        total = float(disk.get("total_bytes", 0) or 0)
        used = float(disk.get("used_bytes", 0) or 0)
        used_pct = disk.get("used_pct")
        if used_pct is None:
            used_pct = used * 100 / total if total else None
        conditions["disk_used"] = (
            used_pct is not None and used_pct >= self.config.disk_used_pct,
            0,
            f"Disk usage is {used_pct:.1f}%" if used_pct is not None else "Disk usage is high",
            {"disk_used_pct": used_pct},
        )
        forecast = snapshot.get("forecast_days")
        conditions["disk_forecast"] = (
            forecast is not None and float(forecast) < self.config.disk_forecast_days,
            0,
            f"Disk is forecast full in {float(forecast):.1f} days"
            if forecast is not None
            else "Disk capacity forecast is low",
            {"disk_forecast_days": forecast},
        )
        for target_id, health in snapshot.get("outputs", {}).items():
            failures = int(getattr(health, "consecutive_failures", 0))
            conditions[f"target_failures:{target_id}"] = (
                failures >= self.config.target_failures,
                0,
                f"Alert target {target_id} has {failures} consecutive failures",
                {"target_id": target_id, "target_failures": failures},
            )
        for key, (truth, duration, detail, numbers) in conditions.items():
            await self._evaluate_one(key, truth, duration, detail, numbers, now)

    async def _evaluate_one(  # noqa: PLR0913,PLR0917 -- condition evaluation needs its complete payload.
        self,
        key: str,
        truth: bool,
        duration: float,
        detail: str,
        numbers: dict[str, object],
        now: float,
    ) -> None:
        state = self.latches.setdefault(key, _Latch())
        if not truth:
            if state.latched:
                state.latched = False
                await self._send(key, "resolved", detail, numbers, state, now)
            state.true_since = None
            return
        if state.true_since is None:
            state.true_since = now
        if not state.latched and now - state.true_since >= duration:
            if self._notice_allowed(state, now):
                state.latched = True
                await self._send(key, "firing", detail, numbers, state, now)
            else:
                state.dropped += 1
                LOGGER.warning(
                    "admin alert firing dropped",
                    extra={"condition": key, "count": state.dropped},
                )
        elif state.latched and self._notice_allowed(state, now):
            await self._send(key, "firing", detail, numbers, state, now)
        elif (
            state.latched
            and state.last_notice is not None
            and now - state.last_notice >= self.config.min_interval_s
        ):
            state.dropped += 1
            LOGGER.warning(
                "admin alert reminder dropped",
                extra={"condition": key, "count": state.dropped},
            )

    async def _send(  # noqa: PLR0913,PLR0917 -- delivery needs condition state and payload details.
        self,
        key: str,
        status: str,
        detail: str,
        numbers: dict[str, object],
        state: _Latch,
        now: float,
    ) -> None:
        if key in self._inflight:
            return
        self._inflight.add(key)
        try:
            since = state.true_since if status != "resolved" else now
            payload: dict[str, object] = {
                "kind": "admin",
                "condition": key,
                "state": status,
                "severity": "warning",
                "since": datetime.fromtimestamp(since or now, UTC).isoformat(),
                "detail": detail,
                **numbers,
            }
            await self.dispatcher.dispatch_admin(payload, self.config.targets)
            if status == "firing":
                state.last_notice = now
                self._hourly.append(now)
        finally:
            self._inflight.discard(key)
