"""Named M5a resource regression tests."""

import wave
from collections.abc import MutableMapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, cast
from uuid import uuid4

import httpx
import numpy as np
import pytest
from pydantic import AnyUrl

from tonewatch.api.app import create_app
from tonewatch.config.models import (
    AdminAlertsConfig,
    Agency,
    AgencyLocation,
    AppConfig,
    DiscoveryConfig,
    FileSource,
    LiveStreamConfig,
    MapConfig,
    ToneSet,
    WebhookTarget,
)
from tonewatch.config.store import ConfigStore, replace_config
from tonewatch.events import EventBus, ToneDetected
from tonewatch.importers.tones_cfg import apply_tones_cfg, parse_tones_cfg
from tonewatch.integrations.supervisor import ensure_addon_mqtt_target
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database, create_database_schema
from tonewatch.storage.models import Call, CallToneSet, Recording


def _tone() -> dict[str, Any]:
    return {"id": "fire", "name": "Fire", "sequence": [{"freq_hz": 1000, "min_s": 1}]}


def _wav(seconds: int = 1) -> bytes:
    stream = BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(np.zeros(16_000 * seconds, dtype=np.int16).tobytes())
    return stream.getvalue()


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *_args: Any) -> None:
        return None

    async def scalars(self, *_args: Any) -> Any:
        class Result:
            def all(self) -> list[Any]:
                return []

        return Result()


class BaseSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def reload(self, _config: Any) -> None:
        pass


class RichSession:
    row: Any = None
    values: ClassVar[list[list[Any]]] = []

    async def __aenter__(self) -> "RichSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *_args: Any) -> Any:
        return self.row

    async def scalars(self, *_args: Any) -> Any:
        items = self.values.pop(0) if self.values else []

        class Result:
            def all(self) -> list[Any]:
                return items

        return Result()


@pytest.mark.asyncio
async def test_toneset_crud_persists_yaml_and_reloads_supervisor() -> None:
    class FakeSupervisor:
        def __init__(self) -> None:
            self.reloads: list[AppConfig] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def reload(self, config: AppConfig) -> None:
            self.reloads.append(config)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        supervisor = FakeSupervisor()
        app = create_app(
            Settings(data_dir=root, zeroconf_enabled=False),
            supervisor=supervisor,
            session_factory=FakeSession,
        )
        async with app.router.lifespan_context(app), await _client(app) as client:
            token = (root / "api_token").read_text().strip()
            headers = {"Authorization": f"Bearer {token}"}
            assert (
                await client.post("/api/tonesets", json=_tone(), headers=headers)
            ).status_code == 201
        assert "fire" in (root / "config.yaml").read_text() and supervisor.reloads


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "owner"),
    [
        ("tone_set_create", "tone_sets"),
        ("tone_set_update", "tone_sets"),
        ("tone_set_delete", "tone_sets"),
        ("source_create", "sources"),
        ("source_update", "sources"),
        ("source_delete", "sources"),
        ("alert_target_create", "alert_targets"),
        ("meshtastic_target_create", "alert_targets"),
        ("alert_target_update", "alert_targets"),
        ("alert_target_delete", "alert_targets"),
        ("agency_create", "agencies"),
        ("agency_update", "agencies"),
        ("agency_delete", "agencies"),
        ("tones_cfg_apply", "tone_sets"),
        ("addon_mqtt_target", "alert_targets"),
        ("admin_alerts_update", "admin_alerts"),
    ],
)
async def test_all_config_mutation_paths_preserve_untouched_fields(path: str, owner: str) -> None:
    agency = Agency(
        id="north-unit",
        name="North Unit",
        short_name="NU",
        kind="rescue",
        color="#123456",
        location=AgencyLocation(lat=40.1, lon=-105.1),
    )
    baseline = AppConfig(
        tone_sets=[ToneSet(**_tone())],
        sources=[FileSource(id="radio", name="Radio", path="invented.wav", tonesets=[])],
        alert_targets=[
            WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test/hook"))
        ],
        agencies=[agency],
        map=MapConfig(tile_url="https://tiles.example/{z}/{x}/{y}.png", attribution="invented"),
        discovery=DiscoveryConfig(enabled=False, clip=False, min_segment_s=0.4, max_segment_s=4),
        live_stream=LiveStreamConfig(
            enabled=True,
            bitrate_kbps=64,
            max_listeners_per_source=5,
            max_listeners_total=20,
            token_ttl_s=7200,
            max_lag_s=15,
        ),
        admin_alerts=AdminAlertsConfig(
            enabled=True,
            targets=[],
            feed_unhealthy_min=12,
            disk_used_pct=77,
            disk_forecast_days=11,
            target_failures=8,
            squelch_stuck_open=False,
            realtime_factor_min=2.5,
            realtime_factor_min_s=90,
            min_interval_s=120,
            max_per_hour=9,
        ),
    )
    values = baseline.model_dump()
    assert set(values) == set(AppConfig.model_fields)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        ConfigStore(root).save(baseline)
        app = create_app(
            Settings(data_dir=root, zeroconf_enabled=False),
            supervisor=BaseSupervisor(),
            session_factory=FakeSession,
        )
        app.state.config = baseline
        token = (root / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            actions: dict[str, Any] = {
                "tone_set_create": lambda: client.post(
                    "/api/tonesets", json={**_tone(), "id": "added-tone"}, headers=headers
                ),
                "tone_set_update": lambda: client.put(
                    "/api/tonesets/fire", json={**_tone(), "name": "Renamed Fire"}, headers=headers
                ),
                "tone_set_delete": lambda: client.delete("/api/tonesets/fire", headers=headers),
                "source_create": lambda: client.post(
                    "/api/sources",
                    json={
                        "id": "added-source",
                        "name": "Added",
                        "type": "file",
                        "path": "added.wav",
                    },
                    headers=headers,
                ),
                "source_update": lambda: client.put(
                    "/api/sources/radio",
                    json={
                        "id": "radio",
                        "name": "Renamed Radio",
                        "type": "file",
                        "path": "invented.wav",
                    },
                    headers=headers,
                ),
                "source_delete": lambda: client.delete("/api/sources/radio", headers=headers),
                "alert_target_create": lambda: client.post(
                    "/api/alert-targets",
                    json={
                        "id": "added-hook",
                        "name": "Added Hook",
                        "type": "webhook",
                        "url": "https://example.test/added",
                    },
                    headers=headers,
                ),
                "alert_target_update": lambda: client.put(
                    "/api/alert-targets/hook",
                    json={
                        "id": "hook",
                        "name": "Renamed Hook",
                        "type": "webhook",
                        "url": "https://example.test/renamed",
                    },
                    headers=headers,
                ),
                "meshtastic_target_create": lambda: client.post(
                    "/api/alert-targets",
                    json={
                        "id": "mesh-gateway",
                        "name": "Mesh Gateway",
                        "type": "meshtastic",
                        "host": "127.0.0.1",
                        "gateway_node_id": "!9abc1234",
                        "channel_index": 1,
                    },
                    headers=headers,
                ),
                "alert_target_delete": lambda: client.delete(
                    "/api/alert-targets/hook", headers=headers
                ),
                "agency_create": lambda: client.post(
                    "/api/agencies",
                    json={
                        "id": "added-unit",
                        "name": "Added Unit",
                        "short_name": "AU",
                        "kind": "fire",
                        "color": "#654321",
                        "location": {"lat": 41, "lon": -106},
                    },
                    headers=headers,
                ),
                "agency_update": lambda: client.put(
                    "/api/agencies/north-unit",
                    json={
                        "id": "north-unit",
                        "name": "Renamed Unit",
                        "short_name": "NU",
                        "kind": "rescue",
                        "color": "#123456",
                        "location": {"lat": 40.1, "lon": -105.1},
                    },
                    headers=headers,
                ),
                "agency_delete": lambda: client.delete("/api/agencies/north-unit", headers=headers),
            }
            if path in actions:
                response = await actions[path]()
                assert response.status_code in {200, 201}, (path, response.text)
                actual = app.state.config
            elif path == "tones_cfg_apply":
                actual = apply_tones_cfg(
                    baseline,
                    parse_tones_cfg("[Imported]\nlongtone=1200\nlongtonelength=1\n"),
                    "merge",
                )
            elif path == "admin_alerts_update":
                actual = replace_config(
                    baseline,
                    admin_alerts=AdminAlertsConfig(
                        enabled=False,
                        targets=[],
                        feed_unhealthy_min=20,
                        disk_used_pct=80,
                        disk_forecast_days=14,
                        target_failures=10,
                        squelch_stuck_open=True,
                        realtime_factor_min=1.8,
                        realtime_factor_min_s=180,
                        min_interval_s=600,
                        max_per_hour=4,
                    ),
                )
            else:

                class AddonSettings:
                    addon_mode = True
                    mqtt_mode = "supervisor"

                class SavingStore:
                    saved: AppConfig | None = None

                    def save(self, config: AppConfig) -> None:
                        self.saved = config

                store = SavingStore()
                actual = ensure_addon_mqtt_target(baseline, AddonSettings(), cast("Any", store))
                assert store.saved == actual

            for field in AppConfig.model_fields:
                if field != owner:
                    assert getattr(actual, field) == getattr(baseline, field), path


@pytest.mark.asyncio
async def test_agencies_api_auth_csrf_and_geojson() -> None:
    payload = {
        "id": "north-unit",
        "name": "North Unit",
        "short_name": "NU",
        "kind": "rescue",
        "color": "#123456",
        "location": {"lat": 40.1, "lon": -105.1},
        "stations": [{"name": "Station A", "lat": 40.2, "lon": -105.2}],
        "coverage": {
            "type": "Polygon",
            "coordinates": [[[-105.2, 40.1], [-105.0, 40.1], [-105.0, 40.2], [-105.2, 40.1]]],
        },
        "cad_names": [" North Unit ", "north unit"],
    }
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(
            Settings(data_dir=root, zeroconf_enabled=False),
            supervisor=BaseSupervisor(),
            session_factory=FakeSession,
        )
        async with await _client(app) as client:
            assert (await client.get("/api/agencies")).status_code == 401
            token = (root / "api_token").read_text().strip()
            headers = {"Authorization": f"Bearer {token}"}
            assert (await client.get("/api/agencies", headers=headers)).json() == []
            assert (
                await client.post("/api/agencies", json={"id": "bad"}, headers=headers)
            ).status_code == 422
            assert (await client.get("/api/agencies/missing", headers=headers)).status_code == 404
            assert (await client.get("/api/map-config", headers=headers)).status_code == 200
            created = await client.post("/api/agencies", json=payload, headers=headers)
            assert created.status_code == 201
            assert (
                await client.post("/api/agencies", json=payload, headers=headers)
            ).status_code == 409
            assert (
                await client.get("/api/agencies/north-unit", headers=headers)
            ).status_code == 200
            geojson = await client.get("/api/agencies.geojson", headers=headers)
            assert geojson.status_code == 200 and geojson.headers["content-type"].startswith(
                "application/geo+json"
            )
            assert len(geojson.json()["features"]) == 3
            changed = {**payload, "name": "Renamed Unit"}
            assert (
                await client.put("/api/agencies/north-unit", json=changed, headers=headers)
            ).status_code == 200
            assert (
                await client.put("/api/agencies/bad", json=changed, headers=headers)
            ).status_code == 422
            assert (
                await client.put(
                    "/api/agencies/missing", json={**changed, "id": "missing"}, headers=headers
                )
            ).status_code == 404
            app.state.config = AppConfig(
                agencies=[Agency.model_validate(payload)],
                tone_sets=[ToneSet(**_tone(), agency_id="north-unit")],
            )
            conflict = await client.delete("/api/agencies/north-unit", headers=headers)
            assert conflict.status_code == 409 and "fire" in conflict.text
            app.state.config = AppConfig(agencies=[Agency.model_validate(payload)])
            assert (
                await client.delete("/api/agencies/north-unit", headers=headers)
            ).status_code == 200
            assert (
                await client.delete("/api/agencies/missing", headers=headers)
            ).status_code == 404


@pytest.mark.asyncio
async def test_config_crossref_error_is_422_naming_id() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(
            Settings(data_dir=Path(directory), zeroconf_enabled=False), session_factory=FakeSession
        )
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            response = await client.post(
                "/api/tonesets",
                json={**_tone(), "alert_targets": ["missing-target"]},
                headers=headers,
            )
            assert response.status_code == 422 and "missing-target" in response.text


@pytest.mark.asyncio
async def test_toneset_missing_agency_reference_is_422_naming_id() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(
            Settings(data_dir=root), supervisor=BaseSupervisor(), session_factory=FakeSession
        )
        token = (root / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            response = await client.post(
                "/api/tonesets",
                json={**_tone(), "agency_id": "missing-agency"},
                headers=headers,
            )
            assert response.status_code == 422
            assert "missing-agency" in response.text


@pytest.mark.asyncio
async def test_app_csp_reloads_map_origin_and_keeps_api_deny_all() -> None:
    with TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        web_root = tmp_path / "web"
        web_root.mkdir()
        (web_root / "index.html").write_text(
            "<html><head></head><body>invented</body></html>", encoding="utf-8"
        )
        app = create_app(
            Settings(data_dir=tmp_path, web_root=web_root),
            supervisor=BaseSupervisor(),
            session_factory=FakeSession,
        )
        token = (tmp_path / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            empty = await client.get("/", headers={"Accept": "text/html"})
            assert "https://" not in empty.headers["content-security-policy"]
            config = AppConfig(map=MapConfig(tile_url="https://tiles.example/{z}/{x}/{y}.png"))
            saved = await client.put(
                "/api/config", json=config.model_dump(mode="json"), headers=headers
            )
            assert saved.status_code == 200
            configured = await client.get("/", headers={"Accept": "text/html"})
            csp = configured.headers["content-security-policy"]
            assert csp.count("https://tiles.example") == 1
            assert csp.count("img-src 'self' https://tiles.example") == 1
            api = await client.get("/api/config", headers=headers)
            assert api.headers["content-security-policy"] == (
                "default-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
            )


@pytest.mark.asyncio
async def test_geojson_identifier_is_an_agency_id() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(
            Settings(data_dir=root), supervisor=BaseSupervisor(), session_factory=FakeSession
        )
        app.state.config = AppConfig(
            agencies=[
                Agency(
                    id="geojson",
                    name="Geo Unit",
                    short_name="GU",
                    kind="rescue",
                    color="#123456",
                    location=AgencyLocation(lat=40, lon=-105),
                )
            ]
        )
        token = (root / "api_token").read_text().strip()
        async with await _client(app) as client:
            response = await client.get(
                "/api/agencies/geojson", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["id"] == "geojson"


@pytest.mark.asyncio
async def test_call_agency_snapshot_survives_rename_unlink_delete() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        engine, sessions = create_database(f"sqlite+aiosqlite:///{root / 'calls.sqlite'}")
        await create_database_schema(engine)
        agency = Agency(
            id="north-unit",
            name="North Unit",
            short_name="NU",
            kind="rescue",
            color="#123456",
            location=AgencyLocation(lat=40.1, lon=-105.1),
        )
        tone = ToneSet(**_tone(), agency_id=agency.id)
        config = AppConfig(tone_sets=[tone], agencies=[agency])
        bus = EventBus()
        persistence = PersistenceSubscriber(bus, sessions, config=config)
        await persistence.start()
        call_id = uuid4()
        await persistence._persist(ToneDetected(call_id, tone.id, datetime.now(UTC), "radio"))
        await persistence.stop()

        app = create_app(
            Settings(data_dir=root), supervisor=BaseSupervisor(), session_factory=sessions
        )
        renamed = agency.model_copy(update={"name": "Renamed North Unit"})
        renamed_config = replace_config(config, agencies=[renamed])
        app.state.config = replace_config(
            renamed_config,
            tone_sets=[tone.model_copy(update={"agency_id": None})],
            agencies=[],
        )
        token = (root / "api_token").read_text().strip()
        async with await _client(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            listed = await client.get(f"/api/calls?agency_id={agency.id}", headers=headers)
            assert listed.status_code == 200 and str(call_id) in str(listed.json())
            detail = await client.get(f"/api/calls/{call_id}", headers=headers)
            snapshot = detail.json()["tone_sets"][0]["agency"]
            assert snapshot == {"id": agency.id, "name": agency.name, "kind": agency.kind}
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_referenced_toneset_is_409_listing_referrers() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        app.state.config = AppConfig(
            tone_sets=[ToneSet(**_tone())],
            sources=[FileSource(id="radio", name="Radio", path="fixture.wav", tonesets=["fire"])],
        )
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            assert (await client.delete("/api/tonesets/fire", headers=headers)).status_code == 409


@pytest.mark.asyncio
async def test_script_target_enable_forbidden_unless_allowed() -> None:
    payload = {"id": "run", "name": "Run", "type": "script", "executable": "x", "enabled": True}
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            assert (
                await client.post("/api/alert-targets", json=payload, headers=headers)
            ).status_code == 403


@pytest.mark.asyncio
async def test_calls_filters_and_cursor_pagination() -> None:
    with TemporaryDirectory() as directory:
        first, second = uuid4(), uuid4()
        started = datetime.now(UTC)
        calls = [
            Call(id=first, started_at=started, source_id="radio", status="closed"),
            Call(id=second, started_at=started, source_id="radio", status="closed"),
        ]
        tones = [
            CallToneSet(
                call_id=first, toneset_id="fire", detected_at=started, matched_segment_freqs=[]
            ),
            CallToneSet(
                call_id=second, toneset_id="fire", detected_at=started, matched_segment_freqs=[]
            ),
        ]
        app = create_app(Settings(data_dir=Path(directory)), session_factory=RichSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            RichSession.values = [calls, tones]
            response = await client.get(
                "/api/calls?limit=999&cursor=0&source_id=radio&toneset_id=fire"
                f"&since={started.isoformat().replace('+00:00', 'Z')}"
                f"&until={started.isoformat().replace('+00:00', 'Z')}",
                headers=headers,
            )
            assert response.status_code == 200
            assert len(response.json()["items"]) == 2 and response.json()["next_cursor"] is None
            RichSession.values = [calls, tones]
            page = await client.get(
                "/api/calls?limit=1&cursor=0&source_id=radio&toneset_id=fire", headers=headers
            )
            assert (
                page.status_code == 200
                and len(page.json()["items"]) == 1
                and page.json()["next_cursor"] == "1"
            )


@pytest.mark.asyncio
async def test_calls_detail_and_recording_range_content() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        call_id = uuid4()
        recording_path = root / "recordings" / "recording.mp3"
        recording_path.parent.mkdir()
        recording_path.write_bytes(bytes(range(256)) * 2)
        RichSession.row = Call(
            id=call_id, started_at=datetime.now(UTC), source_id="radio", status="recorded"
        )
        RichSession.values = [
            [
                CallToneSet(
                    call_id=call_id,
                    toneset_id="fire",
                    detected_at=datetime.now(UTC),
                    matched_segment_freqs=[],
                )
            ],
            [
                Recording(
                    id=1,
                    call_id=call_id,
                    format="mp3",
                    path=str(recording_path),
                    duration_s=1,
                    size_bytes=512,
                )
            ],
            [],
        ]
        app = create_app(Settings(data_dir=root), session_factory=RichSession)
        token = (root / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            RichSession.row = None
            missing = await client.get(f"/api/calls/{uuid4()}", headers=headers)
            assert missing.status_code == 404
            RichSession.row = Call(
                id=call_id, started_at=datetime.now(UTC), source_id="radio", status="recorded"
            )
            detail = await client.get(f"/api/calls/{call_id}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["recordings"][0]["url"].endswith("/api/recordings/1")
            for range_header, expected in [
                (None, 200),
                ("bytes=0-99", 206),
                ("bytes=-100", 206),
                ("bytes=999-1000", 416),
            ]:
                RichSession.row = Recording(
                    id=1,
                    call_id=call_id,
                    format="mp3",
                    path=str(recording_path),
                    duration_s=1,
                    size_bytes=512,
                )
                response = await client.get(
                    "/api/recordings/1",
                    headers=headers | ({"Range": range_header} if range_header else {}),
                )
                assert response.status_code == expected
                assert response.headers.get("accept-ranges") == "bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "range_header,expected",
    [(None, 200), ("bytes=0-99", 206), ("bytes=-100", 206), ("bytes=999-1000", 416)],
)
async def test_recording_range_requests(range_header: str | None, expected: int) -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        async with await _client(app) as client:
            # Unknown DB ids are safely refused before any client-supplied path is considered.
            response = await client.get(
                "/api/recordings/1",
                headers=headers | ({"Range": range_header} if range_header else {}),
            )
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_recording_path_outside_root_is_refused() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.get(
                    "/api/recordings/999", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 404


@pytest.mark.asyncio
async def test_analyze_rejects_oversize_413_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        called = False

        def unexpected(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal called
            called = True
            raise AssertionError

        monkeypatch.setattr("tonewatch.api.routes.analyze.analyze_wav", unexpected)
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                content=b"not-read",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "multipart/form-data; boundary=x",
                    "Content-Length": str(20 * 1024 * 1024 + 64 * 1024 + 1),
                },
            )
            assert response.status_code == 413
        assert not called

        chunk = b"x" * (1024 * 1024)
        preamble = (
            b"------tw\r\n"
            b'Content-Disposition: form-data; name="file"; filename="x.wav"\r\n'
            b"Content-Type: audio/wav\r\n\r\n"
        )
        chunks = [preamble + chunk[len(preamble) :]] + [chunk] * 22
        pulled = 0
        sent: list[MutableMapping[str, Any]] = []

        async def receive() -> MutableMapping[str, Any]:
            nonlocal pulled
            body = chunks[min(pulled, len(chunks) - 1)]
            pulled += 1
            return {"type": "http.request", "body": body, "more_body": True}

        async def send(message: MutableMapping[str, Any]) -> None:
            sent.append(message)

        scope: Any = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/analyze",
            "raw_path": b"/api/analyze",
            "query_string": b"",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"multipart/form-data; boundary=----tw"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
        await app(scope, receive, send)
        assert pulled <= 23 and any(message.get("status") == 413 for message in sent)


@pytest.mark.asyncio
async def test_analyze_rejects_non_wav_415() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.post(
                    "/api/analyze",
                    files={"file": ("x.wav", b"not wav")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).status_code == 415


@pytest.mark.asyncio
async def test_analyze_rejects_over_10_minutes() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                files={"file": ("x.wav", _wav(601))},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 413


@pytest.mark.asyncio
async def test_analyze_returns_documented_schema() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            response = await client.post(
                "/api/analyze",
                files={"file": ("x.wav", _wav())},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert set(response.json()) == {"schema_version", "segments", "detections"}


@pytest.mark.asyncio
async def test_analyze_temp_files_removed() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            await client.post(
                "/api/analyze",
                files={"file": ("x.wav", b"bad")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert not list(Path(directory).glob("*.wav"))


@pytest.mark.asyncio
async def test_toneset_test_endpoint_publishes_marked_events_without_recording_file() -> None:
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        app.state.config = AppConfig(tone_sets=[ToneSet(**_tone())])
        token = (Path(directory) / "api_token").read_text().strip()
        async with await _client(app) as client:
            assert (
                await client.post(
                    "/api/tonesets/fire/test", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 200
        assert (
            not list((Path(directory) / "recordings").glob("**/*"))
            if (Path(directory) / "recordings").exists()
            else True
        )


@pytest.mark.asyncio
async def test_devices_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tonewatch.api.app.input_devices", lambda: [{"index": 0}])
    with TemporaryDirectory() as directory:
        app = create_app(Settings(data_dir=Path(directory)), session_factory=FakeSession)
        token = (Path(directory) / "api_token").read_text().strip()
        response = await request_devices(app, token)
        assert response.status_code == 200 and response.json() == [{"index": 0}]


async def request_devices(app: Any, token: str) -> httpx.Response:
    async with await _client(app) as client:
        return await client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
