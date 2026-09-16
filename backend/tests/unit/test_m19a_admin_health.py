"""M19a health metric contracts (A--F, J)."""

import asyncio
import importlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import numpy as np
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import AnyUrl
from sqlalchemy import create_engine, text

from tonewatch.admin.health import (
    ChannelHealth,
    OutputHealth,
    RealtimeFactor,
    StorageScanner,
    event_bus_health,
    storage_forecast,
)
from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.config.models import AppConfig, FileSource, WebhookTarget
from tonewatch.dsp.engine import EngineOutput
from tonewatch.events import EventBus, FeedHealthChanged, SquelchChanged
from tonewatch.pipeline.channel import Channel
from tonewatch.sources.base import AudioFrame


class SenderFailureError(Exception):
    """Synthetic sender failure for the dispatcher regression test."""


def test_m19a_a_realtime_factor_ewma_window() -> None:
    now = [0.0]
    factor = RealtimeFactor(lambda: now[0], half_life_s=30)
    assert factor.observe(1, 0.1) == pytest.approx(10)
    now[0] = 30
    assert factor.observe(1, 1) == pytest.approx(5.5, abs=0.01)


def test_m19a_b_channel_health_counts_dropped_and_late_frames() -> None:
    health = ChannelHealth()
    health.observe_frame(1.0, 0.1, dropped=2)
    health.observe_frame(1.0, 1.1, dropped=1)
    assert health.dropped_frames == 3
    assert health.late_frames == 1


def test_m19a_item3_channel_run_updates_health_without_changing_detection_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Source:
        dropped = 2

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def __aenter__(self) -> "Source":
            return self

        async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
            return None

        def __aiter__(self) -> AsyncIterator[AudioFrame]:
            async def frames():
                yield AudioFrame(np.ones(1600, dtype=np.float32), 0.0, "radio")

            return frames()

    class Engine:
        def feed(self, _samples: object) -> EngineOutput:
            return EngineOutput((), (), ())

    clock_values = iter((0.0, 1.1))
    monkeypatch.setattr("tonewatch.pipeline.channel.time.perf_counter", lambda: next(clock_values))
    channel = Channel(
        FileSource(id="radio", name="Radio", path="missing.wav"),
        (),
        EventBus(),
        source_factory=lambda _config: Source(),
        engine_factory=lambda _tonesets: Engine(),
    )
    asyncio.run(channel.run())
    assert channel.health.dropped_frames == 2
    assert channel.health.late_frames == 1


def test_m19a_c_feed_health_ring_is_bounded_and_timestamped() -> None:
    health = ChannelHealth()
    at = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(51):
        health.feed_changed(
            FeedHealthChanged("radio", bool(index % 2), str(index)),
            at + timedelta(seconds=index),
        )
    assert len(health.feed_health_history) == 50
    assert health.feed_health_history[0]["reason"] == "1"
    assert health.feed_health_history[-1]["reason"] == "50"
    assert all("at" in item for item in health.feed_health_history)


def test_m19a_d_event_bus_depth_drops_and_lag() -> None:
    async def run() -> None:
        bus = EventBus(max_queue_size=1)
        stalled = bus.subscribe(maxsize=1)
        at = datetime.now(UTC)
        bus.publish(SquelchChanged("radio", True, -20, at))
        bus.publish(SquelchChanged("radio", False, -30, at))
        await asyncio.sleep(0)
        result = event_bus_health(bus)
        assert result[0]["depth"] == 1
        assert result[0]["dropped"] == 1
        assert result[0]["lag_s"] is not None
        bus.unsubscribe(stalled)

    asyncio.run(run())


def test_m19a_e_storage_forecast_exact_zero_and_cap() -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    samples = [(first, 100), (first + timedelta(days=1), 100)]
    assert storage_forecast(1000, samples) == pytest.approx(5)
    assert storage_forecast(1000, [(first, 0), (first + timedelta(days=1), 0)]) is None
    assert storage_forecast(0, samples) == 0
    assert storage_forecast(10_000_000_000, samples) == 3650


def test_m19a_e_disk_scan_is_threaded_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def usage(_path: Path):
        nonlocal calls
        calls += 1
        return type("Usage", (), {"free": 100, "total": 200, "used": 100})()

    monkeypatch.setattr("tonewatch.admin.health.shutil.disk_usage", usage)
    clock = [0.0]
    scanner = StorageScanner(tmp_path, tmp_path / "db", clock=lambda: clock[0])
    asyncio.run(scanner.scan())
    asyncio.run(scanner.scan())
    assert calls == 1
    clock[0] = 60
    asyncio.run(scanner.scan())
    assert calls == 2


def test_m19a_f_output_failure_sequence_is_exact_and_bounded() -> None:
    stats = OutputHealth()
    credential_text = "https://user:password@example.test/hook mqtt-password"
    base = datetime(2026, 1, 1, tzinfo=UTC)
    stats.record(True, base)
    assert stats.consecutive_failures == 0
    for index in range(3):
        stats.record(False, base + timedelta(seconds=index + 1), credential_text)
        assert stats.consecutive_failures == index + 1
    stats.record(True, base + timedelta(seconds=4))
    assert stats.consecutive_failures == 0
    assert stats.last_error is not None and len(stats.last_error) <= 500
    assert credential_text not in stats.last_error


def test_m19a_j_migration_round_trip_keeps_rows_and_defaults_false() -> None:
    with TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'migration.sqlite'}")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE alert_attempts (id INTEGER PRIMARY KEY, call_id TEXT NOT NULL, "
                "target_id TEXT NOT NULL, phase TEXT NOT NULL, attempt_no INTEGER NOT NULL, "
                "ok BOOLEAN NOT NULL, status_code INTEGER, error TEXT, created_at TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alert_attempts "
                "(id, call_id, target_id, phase, attempt_no, ok, created_at) "
                "VALUES (1, 'call', 'target', 'pre_alert', 1, 0, '2026-01-01')"
            )
        revision = importlib.import_module(
            "tonewatch.storage.migrations.versions.0006_alert_attempt_retry"
        )
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                revision.upgrade()
            assert (
                connection.execute(text("SELECT retry FROM alert_attempts WHERE id=1")).scalar_one()
                == 0
            )
            with Operations.context(context):
                revision.downgrade()
            assert "retry" not in {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(alert_attempts)")
            }
            assert connection.execute(text("SELECT count(*) FROM alert_attempts")).scalar_one() == 1
            with Operations.context(context):
                revision.upgrade()
        engine.dispose()


def test_m19a_item3_dispatcher_test_target_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        target = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test"))
        dispatcher = AlertDispatcher(AppConfig(alert_targets=[target]), EventBus())
        with pytest.raises(ValueError, match="not found"):
            await dispatcher.test_target("missing")

        async def fail(*_args: object, **_kwargs: object) -> object:
            raise SenderFailureError("secret failure")  # noqa: TRY003 -- test needs a bounded error payload.

        monkeypatch.setattr(dispatcher, "_send", fail)
        result = await dispatcher.test_target("hook")
        assert result == {"ok": False, "error": "secret failure"}

    asyncio.run(run())


def test_m19a_item3_dispatcher_normal_delivery_updates_stats_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        target = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test"))
        dispatcher = AlertDispatcher(AppConfig(alert_targets=[target]), EventBus())
        sends = 0

        async def send(*_args: object, **_kwargs: object) -> object:
            nonlocal sends
            sends += 1
            return type("Result", (), {"ok": True, "status_code": 204, "error": None})()

        monkeypatch.setattr(dispatcher, "_send", send)
        await dispatcher._dispatch("hook", "pre_alert", uuid4(), {"retry": False})
        assert sends == 1
        assert dispatcher.output_health["hook"].consecutive_failures == 0
        assert dispatcher.output_health["hook"].last_success_at is not None

    asyncio.run(run())


def test_m19a_i_dispatcher_without_database_returns_unknown_attempt() -> None:
    async def run() -> None:
        dispatcher = AlertDispatcher(AppConfig(), EventBus(), None)
        assert await dispatcher.retry_attempt(99) == (
            404,
            {"ok": False, "error": "attempt not found"},
        )
        dispatcher._retrying.add(100)
        assert await dispatcher.retry_attempt(100) == (
            429,
            {"ok": False, "error": "retry_in_flight"},
        )

    asyncio.run(run())
