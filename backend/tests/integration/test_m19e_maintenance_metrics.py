"""M19e maintenance and Prometheus contracts."""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, Request
from sqlalchemy import select

from tonewatch.api.app import create_app
from tonewatch.api.auth import Session
from tonewatch.api.metrics import render_metrics
from tonewatch.api.routes.maintenance import OrphanApply, orphan_apply
from tonewatch.api.routes.maintenance import metrics as metrics_route
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigStore
from tonewatch.recording.retention import (
    RetentionPolicy,
    RetentionService,
    retention_loop,
    safe_recording_path,
)
from tonewatch.settings import MetricsSettings, Settings
from tonewatch.storage.db import (
    checkpoint_database,
    create_database,
    create_database_schema,
    upgrade_database,
    vacuum_database,
)
from tonewatch.storage.models import (
    AlertAttempt,
    AuditEvent,
    CadIncident,
    Call,
    CallToneSet,
    DiscoveredTone,
    Recording,
)


def _settings(root: Path, **kwargs: Any) -> Settings:
    return Settings(
        data_dir=root,
        recordings_root=root / "recordings",
        zeroconf_enabled=False,
        retention=RetentionPolicy(max_age_days=1, max_total_bytes=None, max_count=None),
        **kwargs,
    )


async def _seed(root: Path, *, with_data: bool = True) -> tuple[Path, Any, Any]:
    recordings = root / "recordings"
    recordings.mkdir(parents=True, exist_ok=True)
    engine, sessions = create_database(f"sqlite+aiosqlite:///{root / 'tonewatch.db'}")
    await upgrade_database(engine)
    if with_data:
        old = recordings / "2020" / "old.mp3"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old recording")
        os.utime(old, (1, 1))
        call_id = uuid4()
        old_at = datetime(2020, 1, 1, tzinfo=UTC)
        async with sessions() as session:
            session.add(Call(id=call_id, started_at=old_at, source_id="radio"))
            session.add(
                Recording(call_id=call_id, format="mp3", path=str(old), duration_s=1, size_bytes=13)
            )
            session.add(
                CadIncident(
                    feed_id="cad",
                    incident_id="old",
                    agency_name="agency",
                    agency_key="agency",
                    type_raw="medical",
                    type_key="medical",
                    address_clean="fixture address",
                    cross_streets=[],
                    municipality_raw="town",
                    received_at=old_at,
                    status="closed",
                    first_seen_at=old_at,
                    last_seen_at=old_at,
                )
            )
            clip = recordings / "discovered" / "1.mp3"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"clip")
            session.add(
                DiscoveredTone(
                    id=1,
                    mean_frequencies=[1000],
                    median_durations=[1],
                    duration_samples=[],
                    frequency_minimums=[],
                    frequency_maximums=[],
                    count=1,
                    first_seen=old_at,
                    last_seen=old_at,
                    source_ids=["radio"],
                    status="new",
                    best_clip_recording_path=str(clip),
                )
            )
            await session.commit()
    return recordings, sessions, engine


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _fake_request(app: Any, *, headers: dict[str, str] | None = None) -> Request:
    return cast(
        "Request",
        SimpleNamespace(
            app=app,
            state=SimpleNamespace(auth="test"),
            headers=headers or {},
        ),
    )


async def _wait_for_maintenance_idle(app: Any) -> None:
    await asyncio.wait_for(app.state.maintenance_lock.acquire(), timeout=10)
    app.state.maintenance_lock.release()


async def _stop_daily_retention(app: Any) -> None:
    task = getattr(app.state.supervisor, "_retention_task", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_m19e_a_preview_equals_run_and_second_preview_is_empty(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        assert app.state.maintenance_lock is app.state.retention_service.lock
        token = (tmp_path / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        await app.state.maintenance_lock.acquire()
        try:
            concurrent = await client.post("/api/admin/maintenance/retention/run", headers=headers)
            assert concurrent.status_code == 409
        finally:
            app.state.maintenance_lock.release()
        preview = await client.post("/api/admin/maintenance/retention/preview", headers=headers)
        run = await client.post("/api/admin/maintenance/retention/run", headers=headers)
        again = await client.post("/api/admin/maintenance/retention/preview", headers=headers)
    await engine.dispose()
    assert preview.status_code == run.status_code == 200
    assert preview.json() == run.json()
    assert again.json() == {
        "recordings": {"files": 0, "bytes": 0},
        "calls": 0,
        "cad_incidents": 0,
        "discovered": 0,
        "drills": 0,
    }


@pytest.mark.asyncio
async def test_m19e_a_concurrent_run_and_daily_loop_share_lock(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    service = RetentionService(tmp_path / "recordings", RetentionPolicy())
    entered = asyncio.Event()
    sleep_started = asyncio.Event()

    class SessionContext:
        async def __aenter__(self) -> object:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def close(self) -> None:
            return None

    class DailyService:
        lock = service.lock

        async def enforce(self, _session: object) -> list[Path]:
            entered.set()
            return []

        async def enforce_discovered(self, _session: object) -> list[Path]:
            return []

    async def daily_sleep(_seconds: float) -> None:
        sleep_started.set()
        await asyncio.Event().wait()

    daily_service = DailyService()
    task = asyncio.create_task(
        retention_loop(cast("RetentionService", daily_service), SessionContext, sleep=daily_sleep)
    )
    await service.lock.acquire()
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()
    finally:
        service.lock.release()
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    assert service.lock.locked() is False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_b_checkpoint_vacuum_report_sizes_and_yield(tmp_path: Path) -> None:
    db = tmp_path / "wal.sqlite"
    engine, _sessions = create_database(f"sqlite+aiosqlite:///{db}")
    await create_database_schema(engine)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA wal_autocheckpoint=0")
        await connection.exec_driver_sql("CREATE TABLE wal_probe (value TEXT)")
        await connection.exec_driver_sql("INSERT INTO wal_probe VALUES ('fixture')")
    assert await asyncio.to_thread(Path(f"{db}-wal").is_file)
    db.write_bytes(db.read_bytes() + b"padding")
    before, after = await asyncio.to_thread(vacuum_database, db)
    assert before > 0 and after > 0
    result = await asyncio.to_thread(checkpoint_database, db)
    assert result[0] == 0
    ticks: list[int] = []

    async def ticker() -> None:
        for index in range(3):
            ticks.append(index)
            await asyncio.sleep(0)

    await asyncio.gather(ticker(), asyncio.to_thread(vacuum_database, db))
    assert ticks == [0, 1, 2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_b_vacuum_route_refuses_shared_maintenance_lock(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        token = (tmp_path / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        await app.state.maintenance_lock.acquire()
        try:
            refused = await client.post("/api/admin/maintenance/database/vacuum", headers=headers)
            assert refused.status_code == 409
        finally:
            app.state.maintenance_lock.release()
        response = await client.post("/api/admin/maintenance/database/vacuum", headers=headers)
        assert response.status_code == 200
        assert response.json()["before_bytes"] >= response.json()["after_bytes"] >= 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_b_vacuum_route_maps_sqlite_writer_lock_to_409(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    db_path = tmp_path / "tonewatch.db"
    blocker = sqlite3.connect(db_path)
    blocker.execute("BEGIN IMMEDIATE")
    app = create_app(_settings(tmp_path))
    try:
        async with app.router.lifespan_context(app), await _client(app) as client:
            await _stop_daily_retention(app)
            token = (tmp_path / "api_token").read_text().strip()
            response = await client.post(
                "/api/admin/maintenance/database/vacuum",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 409
            assert "busy" in response.json()["detail"]
    finally:
        blocker.rollback()
        blocker.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_c_orphans_preview_stale_apply_and_exact_cleanup(tmp_path: Path) -> None:
    recordings, sessions, engine = await _seed(tmp_path, with_data=False)
    missing = recordings / "missing.mp3"
    async with sessions() as session:
        session.add(
            Recording(
                call_id=uuid4(),
                format="mp3",
                path=str(missing),
                duration_s=1,
                size_bytes=1,
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    orphan = recordings / "orphan.mp3"
    orphan.write_bytes(b"orphan")
    os.utime(orphan, (1, 1))
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        token = (tmp_path / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        preview = await client.post("/api/admin/maintenance/orphans/preview", headers=headers)
        assert preview.status_code == 200
        body = preview.json()
        assert body["file_count"] == 1 and body["row_count"] == 1
        stale = await client.post(
            "/api/admin/maintenance/orphans/apply",
            headers=headers,
            json={
                "delete_files": True,
                "delete_rows": True,
                "expected_counts": {"file_count": 0, "row_count": 1},
            },
        )
        assert stale.status_code == 409
        applied = await client.post(
            "/api/admin/maintenance/orphans/apply",
            headers=headers,
            json={
                "delete_files": True,
                "delete_rows": True,
                "expected_counts": {"file_count": 1, "row_count": 1},
            },
        )
        assert applied.status_code == 200 and not orphan.exists() and not missing.exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_fix_orphan_apply_rechecks_a_row_added_after_preview(tmp_path: Path) -> None:
    recordings, sessions, engine = await _seed(tmp_path, with_data=False)
    orphan = recordings / "claimed.mp3"
    orphan.write_bytes(b"claimed")
    os.utime(orphan, (1, 1))
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        token = (tmp_path / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        preview = await client.post("/api/admin/maintenance/orphans/preview", headers=headers)
        assert preview.status_code == 200
        async with sessions() as session:
            session.add(
                Recording(
                    call_id=uuid4(),
                    format="mp3",
                    path=str(orphan),
                    duration_s=1,
                    size_bytes=7,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
        applied = await client.post(
            "/api/admin/maintenance/orphans/apply",
            headers=headers,
            json={
                "delete_files": True,
                "expected_counts": {"file_count": 1, "row_count": 0},
            },
        )
        assert applied.status_code == 409
        assert orphan.is_file()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_c_symlink_and_traversal_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    root.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside")
    link = root / "link.mp3"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this Windows host")
    assert not link.is_file() or link.is_symlink()
    with pytest.raises(ValueError):
        safe_recording_path(root, link)
    with pytest.raises(ValueError):
        safe_recording_path(root, root / ".." / "outside.mp3")


def test_m19e_c_mocked_resolve_cannot_escape_recordings_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recordings"
    root.mkdir()
    escape = root / "escape.mp3"
    outside = tmp_path / "outside.mp3"
    original_resolve = Path.resolve

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path == escape:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(ValueError):
        safe_recording_path(root, escape)


@pytest.mark.asyncio
async def test_m19e_c_db_traversal_path_is_explicitly_rejected(tmp_path: Path) -> None:
    recordings, sessions, engine = await _seed(tmp_path, with_data=False)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"must survive")
    orphan = recordings / "real-orphan.mp3"
    orphan.write_bytes(b"delete me")
    os.utime(orphan, (1, 1))
    async with sessions() as session:
        session.add(
            Recording(
                call_id=uuid4(), format="mp3", path="../outside.mp3", duration_s=1, size_bytes=1
            )
        )
        await session.commit()
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        token = (tmp_path / "api_token").read_text().strip()
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.post(
            "/api/admin/maintenance/orphans/preview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["invalid_rows"] == [{"id": 1}]
        assert [item["path"] for item in body["files"]] == ["real-orphan.mp3"]
        applied = await client.post(
            "/api/admin/maintenance/orphans/apply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "delete_files": True,
                "delete_rows": True,
                "expected_counts": {"file_count": 1, "row_count": 0},
            },
        )
        assert applied.status_code == 200
    assert outside.is_file()
    assert not orphan.exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_c_orphan_listing_is_capped_and_relative(tmp_path: Path) -> None:
    recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    for index in range(1001):
        path = recordings / "nested" / f"{index}.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        os.utime(path, (1, 1))
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.post(
            "/api/admin/maintenance/orphans/preview",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["file_count"] == 1001 and len(body["files"]) == 1000
    assert all(not item["path"].startswith(("/", "\\")) for item in body["files"])
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_c_orphan_apply_can_leave_candidates_in_place(tmp_path: Path) -> None:
    recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    orphan = recordings / "keep.mp3"
    orphan.write_bytes(b"keep")
    os.utime(orphan, (1, 1))
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.post(
            "/api/admin/maintenance/orphans/apply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "delete_files": False,
                "delete_rows": False,
                "expected_counts": {"file_count": 1, "row_count": 0},
            },
        )
        direct = await orphan_apply(
            _fake_request(app),
            OrphanApply(
                delete_files=False,
                delete_rows=False,
                expected_counts={"file_count": 1, "row_count": 0},
            ),
        )
    assert response.status_code == 200
    assert response.json() == {"deleted_files": 0, "deleted_rows": 0, "invalid_rows": []}
    assert direct == {"deleted_files": 0, "deleted_rows": 0, "invalid_rows": []}
    assert orphan.is_file()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_c_direct_orphan_apply_validates_and_deletes_rows(tmp_path: Path) -> None:
    recordings, sessions, engine = await _seed(tmp_path, with_data=False)
    missing = recordings / "gone.mp3"
    orphan = recordings / "delete.mp3"
    orphan.write_bytes(b"delete")
    os.utime(orphan, (1, 1))
    async with sessions() as session:
        session.add(
            Recording(
                call_id=uuid4(),
                format="mp3",
                path=str(missing),
                duration_s=1,
                size_bytes=1,
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        await _stop_daily_retention(app)
        request = _fake_request(app)
        with pytest.raises(HTTPException) as stale:
            await orphan_apply(
                request,
                OrphanApply(
                    delete_files=True,
                    delete_rows=True,
                    expected_counts={"file_count": 0, "row_count": 1},
                ),
            )
        assert stale.value.status_code == 409
        result = await orphan_apply(
            request,
            OrphanApply(
                delete_files=True,
                delete_rows=True,
                expected_counts={"file_count": 1, "row_count": 1},
            ),
        )
    assert result == {"deleted_files": 1, "deleted_rows": 1, "invalid_rows": []}
    assert not orphan.exists()
    await engine.dispose()


def test_m19e_e_metrics_golden_escaping_and_cardinality() -> None:
    snapshot = {
        "sources": [
            {
                "id": 'configured\\"\n',
                "realtime_factor": 2,
                "dropped_frames": 3,
                "feed_health_history": [{"healthy": True}],
            }
        ],
        "service": {"subscribers": [{"id": "worker", "depth": 4}]},
        "storage": {"free_bytes": 10, "db_bytes": 20},
        "cad_feeds": [{"id": "cad", "connected": True}],
        "build": {"version": "1.2.3"},
    }
    output = render_metrics(
        snapshot,
        configured_source_ids=['configured\\"\n'],
        configured_feed_ids=["cad"],
        version="1.2.3",
    )
    for name, kind in {
        "tonewatch_detections_total": "counter",
        "tonewatch_alert_attempts_total": "counter",
        "tonewatch_feed_healthy": "gauge",
        "tonewatch_realtime_factor": "gauge",
        "tonewatch_frames_dropped_total": "counter",
        "tonewatch_eventbus_queue_depth": "gauge",
        "tonewatch_disk_free_bytes": "gauge",
        "tonewatch_db_size_bytes": "gauge",
        "tonewatch_cad_feed_connected": "gauge",
        "tonewatch_build_info": "gauge",
    }.items():
        assert f"# HELP {name} " in output
        assert f"# TYPE {name} {kind}\n" in output
    assert 'source_id="configured\\\\\\"\\n"' in output
    assert "unconfigured" not in output
    assert "tonewatch_disk_free_bytes 10\n" in output
    assert 'tonewatch_build_info{version="1.2.3"} 1\n' in output
    for secret in ("fixture-secret", "https://user:pass@example.test/hook", "123 Fictional Street"):
        assert secret not in output
    complete = render_metrics(
        snapshot,
        configured_source_ids=['configured\\"\n'],
        configured_target_ids=["target"],
        configured_toneset_ids=["tones"],
        configured_feed_ids=["cad", "missing"],
        detections={"tones": 2, "not-configured": 99},
        alert_attempts={
            ("target", "pre_alert", "success"): 1,
            ("target", "closed", "failure"): 2,
            ("other", "final", "success"): 3,
        },
        db_size=99,
    )
    assert 'tonewatch_detections_total{toneset_id="tones"} 2' in complete
    assert (
        'tonewatch_alert_attempts_total{target_id="target",phase="pre_alert",outcome="success"} 1'
        in complete
    )
    assert "not-configured" not in complete and 'feed_id="missing"' in complete
    assert "tonewatch_db_size_bytes 99" in complete


@pytest.mark.asyncio
async def test_m19e_e_metrics_auth_matrix_and_disabled(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    call_id = uuid4()
    async with _sessions() as session:
        session.add(Call(id=call_id, started_at=datetime.now(UTC), source_id="radio"))
        session.add(
            CallToneSet(
                call_id=call_id,
                toneset_id="fixture-tone",
                detected_at=datetime.now(UTC),
                matched_segment_freqs=[1000],
            )
        )
        session.add(
            AlertAttempt(
                call_id=call_id,
                target_id="fixture-target",
                phase="final",
                attempt_no=1,
                ok=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _wait_for_maintenance_idle(app)
        assert (await client.get("/metrics")).status_code == 404
    await engine.dispose()
    app = create_app(_settings(tmp_path, metrics=MetricsSettings(enabled=True)))
    async with app.router.lifespan_context(app), await _client(app) as client:
        assert (await client.get("/metrics")).status_code == 401
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        direct = await metrics_route(
            _fake_request(app, headers={"authorization": f"Bearer {token}"})
        )
        assert direct.media_type == "text/plain; version=0.0.4"
    await app.state.engine.dispose()
    app = create_app(_settings(tmp_path, addon_mode=True, metrics=MetricsSettings(enabled=True)))
    transport = httpx.ASGITransport(app=app, client=("172.30.32.2", 1234))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        app.state.auth.sessions["session"] = Session("csrf", app.state.auth.clock())
        assert (
            await client.get("/metrics", headers={"Cookie": "tonewatch_session=session"})
        ).status_code == 401
        assert (
            await client.get("/metrics", headers={"X-Ingress-Path": "/api/hassio_ingress/x"})
        ).status_code == 401
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_m19e_d_maintenance_auth_and_audit(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        path = "/api/admin/maintenance/database/checkpoint"
        assert (await client.post(path)).status_code == 401
        app.state.auth.sessions["session"] = Session("csrf", app.state.auth.clock())
        cookie = "tonewatch_session=session"
        assert (await client.post(path, headers={"Cookie": cookie})).status_code == 403
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.post(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        async with app.state.session_factory() as session:
            events = list((await session.scalars(select(AuditEvent))).all())
        assert any(event.event_type == "database_checkpoint" for event in events)
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_d_every_maintenance_endpoint_has_auth_and_audit(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    app = create_app(_settings(tmp_path))
    endpoints = [
        ("/api/admin/maintenance/retention/preview", None),
        ("/api/admin/maintenance/retention/run", None),
        ("/api/admin/maintenance/database/checkpoint", None),
        ("/api/admin/maintenance/database/vacuum", None),
        ("/api/admin/maintenance/orphans/preview", None),
        (
            "/api/admin/maintenance/orphans/apply",
            {
                "delete_files": True,
                "delete_rows": True,
                "expected_counts": {"file_count": 0, "row_count": 0},
            },
        ),
    ]
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        await _wait_for_maintenance_idle(app)
        app.state.auth.sessions["session"] = Session("csrf", app.state.auth.clock())
        token = (tmp_path / "api_token").read_text().strip()
        for path, body in endpoints:
            assert (await client.post(path, json=body)).status_code == 401
            assert (
                await client.post(path, json=body, headers={"Cookie": "tonewatch_session=session"})
            ).status_code == 403
            response = await client.post(
                path, json=body, headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200, (path, response.text)
        async with app.state.session_factory() as session:
            events = list((await session.scalars(select(AuditEvent))).all())
        assert (
            sum(
                event.event_type.startswith(("retention_", "database_", "orphans_"))
                for event in events
            )
            == 6
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19e_fix_metrics_real_route_matches_fixture_golden(tmp_path: Path) -> None:
    _recordings, _sessions, engine = await _seed(tmp_path, with_data=False)
    fixture_url = "https://user:pass@example.test/fixture-hook"
    fixture_credential = "fixture-webhook-secret"
    config = AppConfig.model_validate(
        {
            "sources": [
                {
                    "type": "file",
                    "id": "fixture-source",
                    "name": "Fixture Source",
                    "path": str(tmp_path / "fixture.wav"),
                    "enabled": False,
                }
            ],
            "tone_sets": [
                {
                    "id": "fixture-tone",
                    "name": "Fixture Tone",
                    "sequence": [{"freq_hz": 1000, "min_s": 1}],
                    "alert_targets": ["fixture-target"],
                }
            ],
            "alert_targets": [
                {
                    "type": "webhook",
                    "id": "fixture-target",
                    "name": "Fixture Target",
                    "url": fixture_url,
                    "secret": fixture_credential,
                    "enabled": False,
                }
            ],
            "cad_feeds": [
                {
                    "id": "fixture-cad",
                    "name": "Fixture CAD",
                    "host": "127.0.0.1",
                    "enabled": False,
                }
            ],
        }
    )
    store = ConfigStore(tmp_path)
    store.save(config)
    app = create_app(
        _settings(tmp_path, metrics=MetricsSettings(enabled=True)),
        store=store,
    )
    async with app.router.lifespan_context(app), await _client(app) as client:
        await _stop_daily_retention(app)
        token = (tmp_path / "api_token").read_text().strip()
        response = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    await engine.dispose()
    assert response.status_code == 200
    normalized = re.sub(r"(tonewatch_disk_free_bytes )\d+", r"\1<D not volatile>", response.text)
    normalized = re.sub(r"(tonewatch_db_size_bytes )\d+", r"\1<D not volatile>", normalized)
    golden = Path(__file__).parents[1] / "golden" / "m19e_metrics.txt"
    assert normalized == golden.read_text(encoding="utf-8")
    for secret in (fixture_url, fixture_credential, "127.0.0.1"):
        assert secret not in response.text


def test_m19e_f_s4_security_file_is_unchanged() -> None:
    assert (
        not __import__("subprocess")
        .run(
            ["git", "diff", "origin/main", "--", "backend/tests/unit/test_s4_security.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        .stdout
    )
