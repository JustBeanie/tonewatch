"""Supervise independent source channels and their persistence consumer."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.events import EventBus, FeedHealthChanged
from tonewatch.pipeline.channel import Channel
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.pipeline.watchdog import Watchdog
from tonewatch.recording.encoder import AudioEncoder
from tonewatch.recording.recorder import CallRecorder
from tonewatch.recording.retention import RetentionService, retention_loop
from tonewatch.sources.base import SourceConfigError

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
    ) -> None:
        self.config, self.bus, self.session_factory = config, bus, session_factory
        self.clock, self.sleep = clock, sleep
        self.settings = settings
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
        self._background_shutdown: set[asyncio.Task[None]] = set()
        self._configs: dict[str, Source] = {}
        self._stopping = False
        self.persistence = PersistenceSubscriber(bus, session_factory)
        self.alerts = AlertDispatcher(
            config,
            bus,
            session_factory,
            settings=settings,
            instance_id=instance_id,
            sleep=sleep,
            jitter=self.jitter,
        )
        self.retention_service = retention_service
        self._retention_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start persistence and one task per enabled source."""
        if self._tasks or self._configs:
            return
        self._stopping = False
        await self.persistence.start()
        if self.settings is not None:
            await self.persistence.reconcile_orphans(self.settings.recording_path)
        await self.alerts.start()
        if self.retention_service is not None:
            self._retention_task = asyncio.create_task(
                retention_loop(self.retention_service, self.session_factory, sleep=self.sleep),
                name="tonewatch-retention",
            )
        for source in self.config.sources:
            if source.enabled:
                self._start_source(source)

    async def stop(self) -> None:
        """Cancel all channel tasks within the bounded shutdown period."""
        self._stopping = True
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
        self._tasks.clear()
        self._configs.clear()
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
        for source_id, old in current.items():
            if source_id not in desired or desired[source_id] != old or tone_sets_changed:
                await self._stop_source(source_id)
        self.config = config
        await self.alerts.reload(config)
        for source_id, source in desired.items():
            if source_id not in current or current[source_id] != source or tone_sets_changed:
                self._start_source(source)

    def _start_source(self, source: Source) -> None:
        self._configs[source.id] = source
        self._tasks[source.id] = asyncio.create_task(
            self._run_source(source), name=f"tonewatch-channel-{source.id}"
        )

    async def _stop_source(self, source_id: str) -> None:
        task = self._tasks.pop(source_id, None)
        self._configs.pop(source_id, None)
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
                )
                await channel.run()
            except asyncio.CancelledError:
                raise
            except SourceConfigError as error:
                self.bus.publish(FeedHealthChanged(source.id, False, str(error)))
                return
            except Exception as error:
                watchdog.on_error(error)
                self.bus.publish(FeedHealthChanged(source.id, False, str(error) or "source_error"))
                if self.clock() - started_at >= MAX_BACKOFF_S:
                    delay = 1.0
                await self.sleep(self.jitter(min(delay, MAX_BACKOFF_S)))
                delay = min(delay * 2, MAX_BACKOFF_S)
            else:
                return
            finally:
                await watchdog.stop()
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)
