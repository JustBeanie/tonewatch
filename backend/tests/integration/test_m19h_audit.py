"""M19h audit filters and keyset pagination contracts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tonewatch.api.app import create_app
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import AuditEvent


@pytest.mark.asyncio
async def test_m19h_audit_filters_and_keyset_cursor(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=sessions)
    token = app.state.auth.token
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with sessions() as session:
        session.add_all(
            [
                AuditEvent(
                    created_at=base,
                    actor="alice",
                    event_type="config_change",
                    resource="config",
                    details={},
                ),
                AuditEvent(
                    created_at=base + timedelta(minutes=1),
                    actor="bob",
                    event_type="login",
                    resource="auth",
                    details={},
                ),
                AuditEvent(
                    created_at=base + timedelta(minutes=2),
                    actor="alice",
                    event_type="config_change",
                    resource="other",
                    details={},
                ),
            ]
        )
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {token}"}
        filtered = await client.get(
            "/api/audit?actor=alice&event_type=config_change&resource=config&since=2025-12-31T23:00:00Z&until=2026-01-01T00:30:00Z",
            headers=headers,
        )
        assert filtered.status_code == 200, filtered.text
        assert [item["actor"] for item in filtered.json()["items"]] == ["alice"]
        reversed_range = await client.get(
            "/api/audit?since=2026-01-02T00:00:00Z&until=2026-01-01T00:00:00Z",
            headers=headers,
        )
        assert reversed_range.status_code == 422
        page_one = await client.get("/api/audit?limit=1", headers=headers)
        assert page_one.status_code == 200
        first = page_one.json()
        assert first["next_cursor"] == str(first["items"][-1]["id"])
        async with sessions() as session:
            session.add(
                AuditEvent(
                    created_at=base + timedelta(minutes=3),
                    actor="new",
                    event_type="new",
                    resource="new",
                    details={},
                )
            )
            await session.commit()
        page_two = await client.get(
            f"/api/audit?limit=2&before_id={first['next_cursor']}", headers=headers
        )
        assert page_two.status_code == 200
        assert not (
            {item["id"] for item in first["items"]}
            & {item["id"] for item in page_two.json()["items"]}
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_m19h_audit_time_filters_require_offsets_and_normalize(tmp_path: Path) -> None:
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    await create_database_schema(engine)
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False), session_factory=sessions)
    token = app.state.auth.token
    boundary = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    async with sessions() as session:
        session.add(
            AuditEvent(
                created_at=boundary, actor="edge", event_type="edge", resource="time", details={}
            )
        )
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {token}"}
        naive = await client.get("/api/audit?since=2026-01-01T00:00:00", headers=headers)
        assert naive.status_code == 422
        utc = await client.get(
            "/api/audit?since=2026-01-01T00:00:00Z&until=2026-01-01T00:00:00Z", headers=headers
        )
        plus_two = await client.get(
            "/api/audit?since=2026-01-01T02:00:00%2B02:00&until=2026-01-01T02:00:00%2B02:00",
            headers=headers,
        )
        assert [item["id"] for item in utc.json()["items"]] == [
            item["id"] for item in plus_two.json()["items"]
        ]
        assert utc.json()["items"]
    await engine.dispose()
