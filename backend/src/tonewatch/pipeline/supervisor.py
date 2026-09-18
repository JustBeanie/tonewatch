"""Supervise independent source channels and their persistence consumer."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiomqtt
from sqlalchemy import select

from tonewatch.admin.alerts import AdminAlertEngine
from tonewatch.admin.health import ChannelHealth, StorageScanner, bounded_error, storage_forecast
from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.cad.correlate import CadCorrelationService
from tonewatch.cad.feed import CadFeedRunner
from tonewatch.events import EventBus, FeedHealthChanged
from tonewatch.pipeline.channel import Channel
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.pipeline.watchdog import Watchdog
from tonewatch.recording.encoder import AudioEncoder
from tonewatch.recording.recorder import CallRecorder
from tonewatch.recording.retention import RetentionService, retention_loop
from tonewatch.sources.base import SourceConfigError
from tonewatch.storage.models import Call, Recording

if TYPE_CHECKING:
    from tonewatch.config.models import AppConfig, Source

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]
ChannelFactory = Callable[..., Channel]
EncoderFactory = Callable[[Path], AudioEncoder]
MAX_BACKOFF_S = 60.0


class Supervisor:
    """Run enabled channels independently, restarting only failed channels."""

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        session_factory: Any,
        clock: Clock = time.time,
        sleep: Sleep = asyncio.sleep,
        *,
        jitter: Jitter | None = None,
        channel_factory: ChannelFactory | None = None,
        shutdown_timeout_s: float = 5,
        retention_service: RetentionService | None = None,
        settings: Any = None,
        instance_id: str = "default",
        source_factory: Callable[[Source], Any] | None = None,
        watchdog_no_data_s: float = 10,
        encoder_factory: EncoderFactory | None = None,
        shutdown_finalize_timeout_s: float | None = None,
        shutdown_drain_timeout_s: float | None = None,
        live_hub: Any = None,
        cad_client_factory: Any = None,
    ) -> None:
        self.config, self.bus, self.session_factory = config, bus, session_factory
        self.settings = settings
        self.live_hub = live_hub
        self.clock, self.sleep = clock, sleep
        self.jitter = jitter or (
            lambda delay: secrets.SystemRandom().uniform(delay * 0.9, delay * 1.1)
        )
        self.channel_factory = channel_factory or Channel
        self.source_factory = source_factory
        self.watchdog_no_data_s = watchdog_no_data_s
        self.encoder_factory = encoder_factory or AudioEncoder
        self.shutdown_finalize_timeout_s = (
            shutdown_finalize_timeout_s
            if shutdown_finalize_timeout_s is not None
            else shutdown_timeout_s / 2
        )
        self.shutdown_drain_timeout_s = (
            shutdown_drain_timeout_s
            if shutdown_drain_timeout_s is not None
            else shutdown_timeout_s / 2
        )
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._drill_active_sources: set[str] = set()
        self._drill_last_started = 0.0
        self._drill_tasks: set[asyncio.Task[None]] = set()
        self._background_shutdown: set[asyncio.Task[None]] = set()
        self._configs: dict[str, Source] = {}
        self._channels: dict[str, Channel] = {}
        self.health: dict[str, ChannelHealth] = {}
        self._stopping = False
        self.persistence = PersistenceSubscriber(
            bus,
            session_factory,
            recordings_root=settings.recording_path if settings is not None else None,
            discovery_clip=bool(getattr(config.discovery, "clip", True)),
            config=config,
        )
        self.alerts = AlertDispatcher(
            config,
            bus,
            session_factory,
            settings=settings,
            instance_id=instance_id,
            sleep=sleep,
            jitter=self.jitter,
        )
        self.admin_alerts = AdminAlertEngine(config.admin_alerts, self.alerts, clock=clock)
        self._admin_task: asyncio.Task[None] | None = None
        self._admin_scanner = (
            StorageScanner(settings.recording_path, settings.data_dir / "tonewatch.db")
            if settings is not None
            else None
        )
        self.retention_service = retention_service
        self._retention_task: asyncio.Task[None] | None = None
        self._cad_tasks: dict[str, asyncio.Task[None]] = {}
        self._cad_configs: dict[str, Any] = {}
        self.cad_health: dict[str, Any] = {}
        self._cad_client_factory = cad_client_factory or self._default_cad_client
        self.cad_correlation = CadCorrelationService(
            config, bus, session_factory, clock=lambda: datetime.now(UTC)
        )

    def _default_cad_client(self, feed: Any) -> Any:
        """Build an aiomqtt client from a feed; tests inject this factory."""
        target = next(
            (item for item in self.config.alert_targets if item.id == feed.mqtt_target_id), None
        )
        host = feed.host or getattr(target, "hostname", "localhost")
        return aiomqtt.Client(
            hostname=host,
            port=feed.port if feed.host else getattr(target, "port", feed.port),
            username=feed.username if feed.host else getattr(target, "username", None),
            password=feed.password if feed.host else getattr(target, "password", None),
            tls_context=None,
        )

    async def start(self) -> None:
        """Start persistence and one task per enabled source."""
        if self._tasks or self._configs:
            return
        self._stopping = False
        await self.persistence.start()
        await self.cad_correlation.start()
        if self.settings is not None:
            await self.persistence.reconcile_orphans(self.settings.recording_path)
        await self.alerts.start()
        await self.admin_alerts.start()
        if self.config.admin_alerts.enabled:
            self._admin_task = asyncio.create_task(
                self._admin_loop(), name="tonewatch-admin-alerts"
            )
        if self.retention_service is not None:
            self._retention_task = asyncio.create_task(
                retention_loop(self.retention_service, self.session_factory, sleep=self.sleep),
                name="tonewatch-retention",
            )
        for source in self.config.sources:
            if source.enabled:
                self._start_source(source)
        self._apply_cad_feeds()

    async def stop(self) -> None:  # noqa: PLR0915 -- bounded shutdown lifecycle is intentionally explicit.
        """Cancel all channel tasks within the bounded shutdown period."""
        self._stopping = True
        for task in tuple(self._drill_tasks):
            task.cancel()
        if self._drill_tasks:
            await asyncio.gather(*self._drill_tasks, return_exceptions=True)
        self._drill_tasks.clear()
        self._drill_active_sources.clear()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        drain_budget = max(0.0, self.shutdown_drain_timeout_s)
        if tasks:
            channel_join = asyncio.gather(*tasks, return_exceptions=True)
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(channel_join), self.shutdown_finalize_timeout_s
                )

            async def finish_and_drain() -> None:
                await channel_join
                await self.persistence.stop(
                    timeout_s=max(
                        0.0, drain_budget - (asyncio.get_running_loop().time() - drain_started)
                    )
                )

            drain_started = asyncio.get_running_loop().time()
            drain_task = asyncio.create_task(finish_and_drain(), name="tonewatch-shutdown-drain")
            self._background_shutdown.add(drain_task)
            try:
                await asyncio.wait_for(asyncio.shield(drain_task), drain_budget)
            except TimeoutError:
                drain_task.cancel()
                await asyncio.gather(drain_task, return_exceptions=True)
                await self.persistence.stop(timeout_s=0)
            finally:
                self._background_shutdown.discard(drain_task)
        else:
            await self.persistence.stop(timeout_s=drain_budget)
        await self.alerts.stop()
        if self._admin_task is not None:
            self._admin_task.cancel()
            await asyncio.gather(self._admin_task, return_exceptions=True)
            self._admin_task = None
        await self.admin_alerts.stop()
        await self.cad_correlation.stop()
        for task in tuple(self._cad_tasks.values()):
            task.cancel()
        if self._cad_tasks:
            await asyncio.gather(*self._cad_tasks.values(), return_exceptions=True)
        self._cad_tasks.clear()
        self._cad_configs.clear()
        self.cad_health.clear()
        self._tasks.clear()
        self._configs.clear()
        self._channels.clear()
        if self._retention_task is not None:
            self._retention_task.cancel()
            await asyncio.gather(self._retention_task, return_exceptions=True)
            self._retention_task = None
        await self.persistence.stop(timeout_s=0)

    async def wait(self) -> None:
        """Wait for currently running channel lifecycles to finish."""
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reload(self, config: AppConfig) -> None:
        """Apply a source diff without disturbing unchanged channel tasks."""
        desired = {source.id: source for source in config.sources if source.enabled}
        current = dict(self._configs)
        tone_sets_changed = config.tone_sets != self.config.tone_sets
        discovery_changed = config.discovery != self.config.discovery
        for source_id, old in current.items():
            if (
                source_id not in desired
                or desired[source_id] != old
                or tone_sets_changed
                or discovery_changed
            ):
                await self._stop_source(source_id)
        self.config = config
        self.persistence.discovery_clip = bool(getattr(config.discovery, "clip", True))
        self.persistence.config = config
        await self.cad_correlation.reload(config)
        await self.alerts.reload(config)
        await self.admin_alerts.reload(config.admin_alerts)
        if not config.admin_alerts.enabled and self._admin_task is not None:
            self._admin_task.cancel()
            await asyncio.gather(self._admin_task, return_exceptions=True)
            self._admin_task = None
        elif config.admin_alerts.enabled and self._admin_task is None and not self._stopping:
            self._admin_task = asyncio.create_task(
                self._admin_loop(), name="tonewatch-admin-alerts"
            )
        for source_id, source in desired.items():
            if (
                source_id not in current
                or current[source_id] != source
                or tone_sets_changed
                or discovery_changed
            ):
                self._start_source(source)
        self._apply_cad_feeds()

    def _apply_cad_feeds(self) -> None:
        """Hot-apply enabled CAD feed tasks without touching radio channels."""
        desired = {feed.id: feed for feed in self.config.cad_feeds if feed.enabled}
        for feed_id in set(self._cad_tasks) - set(desired):
            self._cad_tasks[feed_id].cancel()
            self._cad_tasks.pop(feed_id, None)
            self._cad_configs.pop(feed_id, None)
            self.cad_health.pop(feed_id, None)
        for feed_id, feed in desired.items():
            if feed_id in self._cad_tasks:
                if self._cad_configs[feed_id] == feed:
                    continue
                self._cad_tasks[feed_id].cancel()
                self._cad_tasks.pop(feed_id, None)
                self._cad_configs.pop(feed_id, None)
                self.cad_health.pop(feed_id, None)
            runner = CadFeedRunner(
                feed,
                client_factory=self._cad_client_factory,
                session_factory=self.session_factory,
                sleep=self.sleep,
                jitter=self.jitter,
            )
            self._cad_configs[feed_id] = feed
            runner.on_incident = self.cad_correlation.on_incident
            self.cad_health[feed_id] = runner.health
            self._cad_tasks[feed_id] = asyncio.create_task(
                runner.run(), name=f"tonewatch-cad-{feed_id}"
            )

    def _start_source(self, source: Source) -> None:
        self._configs[source.id] = source
        self._tasks[source.id] = asyncio.create_task(
            self._run_source(source), name=f"tonewatch-channel-{source.id}"
        )

    async def _stop_source(self, source_id: str) -> None:
        task = self._tasks.pop(source_id, None)
        self._configs.pop(source_id, None)
        self._channels.pop(source_id, None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run_source(self, source: Source) -> None:
        delay = 1.0
        while not self._stopping:
            started_at = self.clock()
            watchdog = Watchdog(
                source.id,
                self.bus,
                clock=self.clock,
                sleep=self.sleep,
                no_data_s=self.watchdog_no_data_s,
            )
            watchdog_task = asyncio.create_task(
                watchdog.run(), name=f"tonewatch-watchdog-{source.id}"
            )
            channel: Channel | None = None
            try:
                channel = self.channel_factory(
                    source,
                    self.config.tone_sets,
                    self.bus,
                    self.clock,
                    recorder_hook=(
                        CallRecorder(
                            self.config.tone_sets,
                            self.encoder_factory(self.settings.recording_path),
                            bus=self.bus,
                        )
                        if self.settings is not None
                        else None
                    ),
                    source_factory=self.source_factory,
                    watchdog=watchdog,
                    source_settings=self.settings,
                    discovery_settings=self.config.discovery,
                    live_hub=self.live_hub,
                    agency_lookup=lambda agency_id: next(
                        (
                            {
                                "id": agency.id,
                                "name": agency.name,
                                "short_name": agency.short_name,
                                "kind": agency.kind,
                                "lat": agency.location.lat,
                                "lon": agency.location.lon,
                            }
                            for agency in self.config.agencies
                            if agency.id == agency_id
                        ),
                        None,
                    ),
                )
                self._channels[source.id] = channel
                self.health.setdefault(source.id, getattr(channel, "health", ChannelHealth()))
                await channel.run()
            except asyncio.CancelledError:
                raise
            except SourceConfigError as error:
                health = self.health.setdefault(source.id, ChannelHealth())
                health.last_error = bounded_error(error)
                self.bus.publish(FeedHealthChanged(source.id, False, str(error)))
                return
            except Exception as error:
                health = self.health.setdefault(source.id, ChannelHealth())
                health.restarts += 1
                health.last_error = bounded_error(error)
                health.last_restart_at = datetime.now(UTC)
                watchdog.on_error(error)
                self.bus.publish(FeedHealthChanged(source.id, False, str(error) or "source_error"))
                if self.clock() - started_at >= MAX_BACKOFF_S:
                    delay = 1.0
                await self.sleep(self.jitter(min(delay, MAX_BACKOFF_S)))
                delay = min(delay * 2, MAX_BACKOFF_S)
            else:
                return
            finally:
                if channel is not None and self._channels.get(source.id) is channel:
                    self._channels.pop(source.id, None)
                await watchdog.stop()
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)

    def source_status(self, source_id: str) -> tuple[bool | None, str | None]:
        """Return live squelch state and last activity timestamp for a source."""
        channel = self._channels.get(source_id)
        if channel is None:
            return None, None
        return channel.squelch_open, (
            channel.last_activity_at.isoformat() if channel.last_activity_at is not None else None
        )

    def source_diagnostics(self, source_id: str) -> dict[str, object] | None:
        """Return channel squelch diagnostics, or None when it is not running."""
        channel = self._channels.get(source_id)
        if channel is None:
            return None
        squelch = channel.squelch
        mode = channel.source_config.squelch.mode
        return {
            "squelch_mode_effective": mode if mode != "off" else None,
            "noise_floor_dbfs": squelch.noise_floor,
            "open_dbfs_effective": squelch.open_threshold_dbfs if mode != "off" else None,
            "close_dbfs_effective": squelch.close_threshold_dbfs if mode != "off" else None,
            "calibrating": squelch.calibrating if mode != "off" else None,
            "stuck_open": squelch.stuck_open if mode != "off" else None,
            "chatter": squelch.chatter if mode != "off" else None,
            "transitions_per_min": squelch.transitions_per_min if mode != "off" else None,
        }

    def channel_for(self, source_id: str) -> Channel | None:
        """Return a currently running channel."""
        return self._channels.get(source_id)

    async def _admin_loop(self) -> None:
        """Poll cached health metrics without doing filesystem work on the loop."""
        while not self._stopping:
            if self._admin_scanner is not None:
                disk = await self._admin_scanner.scan()
            else:
                disk = {}
            forecast = None
            if self.session_factory is not None and disk:
                async with self.session_factory() as session:
                    rows = list(
                        (
                            await session.execute(
                                select(Call.started_at, Recording.size_bytes)
                                .join(Recording, Recording.call_id == Call.id)
                                .order_by(Call.started_at)
                            )
                        ).all()
                    )
                forecast = storage_forecast(
                    cast("int", disk.get("free_bytes", 0)), [(row[0], row[1]) for row in rows]
                )
            await self.admin_alerts.evaluate(
                {
                    "sources": self.health,
                    "outputs": self.alerts.output_health,
                    "disk": disk,
                    "forecast_days": forecast,
                }
            )
            await self.sleep(30.0)
