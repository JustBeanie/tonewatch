"""Supervise independent source channels and their persistence consumer."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from tonewatch.events import EventBus, FeedHealthChanged
from tonewatch.pipeline.channel import Channel
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.pipeline.watchdog import Watchdog
from tonewatch.sources.base import SourceConfigError

if TYPE_CHECKING:
    from tonewatch.config.models import AppConfig, Source

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]
ChannelFactory = Callable[..., Channel]
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
    ) -> None:
        self.config, self.bus, self.session_factory = config, bus, session_factory
        self.clock, self.sleep = clock, sleep
        self.jitter = jitter or (
            lambda delay: secrets.SystemRandom().uniform(delay * 0.9, delay * 1.1)
        )
        self.channel_factory = channel_factory or Channel
        self.shutdown_timeout_s = shutdown_timeout_s
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._configs: dict[str, Source] = {}
        self._stopping = False
        self.persistence = PersistenceSubscriber(bus, session_factory)

    async def start(self) -> None:
        """Start persistence and one task per enabled source."""
        if self._tasks or self._configs:
            return
        self._stopping = False
        await self.persistence.start()
        for source in self.config.sources:
            if source.enabled:
                self._start_source(source)

    async def stop(self) -> None:
        """Cancel all channel tasks within the bounded shutdown period."""
        self._stopping = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                async with asyncio.timeout(self.shutdown_timeout_s):
                    await asyncio.gather(*tasks, return_exceptions=True)
            except TimeoutError:
                pass
        self._tasks.clear()
        self._configs.clear()
        await self.persistence.stop()

    async def wait(self) -> None:
        """Wait for currently running channel lifecycles to finish."""
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reload(self, config: AppConfig) -> None:
        """Apply a source diff without disturbing unchanged channel tasks."""
        desired = {source.id: source for source in config.sources if source.enabled}
        current = dict(self._configs)
        for source_id, old in current.items():
            if source_id not in desired or desired[source_id] != old:
                await self._stop_source(source_id)
        self.config = config
        for source_id, source in desired.items():
            if source_id not in current or current[source_id] != source:
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
            watchdog = Watchdog(source.id, self.bus, clock=self.clock, sleep=self.sleep)
            watchdog_task = asyncio.create_task(
                watchdog.run(), name=f"tonewatch-watchdog-{source.id}"
            )
            try:
                channel = self.channel_factory(
                    source,
                    self.config.tone_sets,
                    self.bus,
                    self.clock,
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
