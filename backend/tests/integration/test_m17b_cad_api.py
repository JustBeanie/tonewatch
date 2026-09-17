"""ASGI coverage for the M17b CAD incident projection."""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tonewatch.api.app import create_app
from tonewatch.config.models import Agency, AgencyLocation, AppConfig
from tonewatch.settings import Settings
from tonewatch.storage.models import CadIncident, CallCadIncident


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class _Session:
    def __init__(self, incidents: list[CadIncident], links: list[CallCadIncident]) -> None:
        self.values: list[list[Any]] = [list(incidents), list(links)]

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def scalars(self, statement: Any) -> _Result:
        values = self.values.pop(0) if self.values else []
        if values and "cad_incidents.agency_key IN" in str(statement):
            values = [value for value in values if value.agency_key == "north"]
        return _Result(values)


class _Supervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def reload(self, _config: Any) -> None:
        pass


def _incident(key: str) -> CadIncident:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CadIncident(
        feed_id="county",
        incident_id=key,
        agency_name=key.title(),
        agency_key=key,
        agency_category="fire",
        type_raw="Invented incident",
        type_key="invented",
        address_clean="Fictional Avenue",
        cross_streets=["Imaginary Road"],
        municipality_raw="Fictional City",
        received_at=now,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )


def _app(root: Path, incidents: list[CadIncident], links: list[CallCadIncident]):
    app = create_app(
        Settings(data_dir=root, zeroconf_enabled=False),
        supervisor=_Supervisor(),
        session_factory=lambda: _Session(incidents, links),
    )
    app.state.config = AppConfig(
        agencies=[
            Agency(
                id="north",
                name="North",
                short_name="N",
                kind="fire",
                color="#000000",
                location=AgencyLocation(lat=0, lon=0),
                cad_names=["north"],
            )
        ]
    )
    return app


@pytest.mark.asyncio
async def test_m17b_incidents_asgi_auth_validation_filter_link_and_no_logging(caplog) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        call_id = uuid4()
        app = _app(
            root,
            [_incident("north"), _incident("south")],
            [CallCadIncident(call_id=call_id, feed_id="county", incident_id="north")],
        )
        token = app.state.auth.token
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/cad/incidents")).status_code == 401
            headers = {"Authorization": f"Bearer {token}"}
            assert (
                await client.get("/api/cad/incidents?limit=0", headers=headers)
            ).status_code == 422
            assert (
                await client.get("/api/cad/incidents?limit=101", headers=headers)
            ).status_code == 422
            assert (
                await client.get("/api/cad/incidents?status=other", headers=headers)
            ).status_code == 422
            response = await client.get("/api/cad/incidents?configured_only=true", headers=headers)
            assert response.status_code == 200
            assert response.json()[0]["call_id"] == str(call_id)
            assert [item["agency_key"] for item in response.json()] == ["north"]
            all_items = await client.get(
                "/api/cad/incidents?configured_only=false", headers=headers
            )
            assert {item["agency_key"] for item in all_items.json()} == {"north", "south"}
        rendered = " ".join(record.getMessage() for record in caplog.records)
        assert "Fictional Avenue" not in rendered and "north" not in rendered
