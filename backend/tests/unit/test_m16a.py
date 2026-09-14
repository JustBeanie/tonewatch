"""M16 agency, GeoJSON, and map-origin invariants."""

import asyncio
import importlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import uuid4

import numpy as np
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import AnyUrl, ValidationError
from sqlalchemy import create_engine, text

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.ha_discovery import HADiscovery
from tonewatch.api.app import _set_api_csp
from tonewatch.api.routes.agencies import agencies_geojson, get_agency
from tonewatch.api.spa import spa_csp
from tonewatch.config.models import (
    Agency,
    AgencyLocation,
    AppConfig,
    DiscoveryConfig,
    FileSource,
    MapConfig,
    MqttTarget,
    SquelchConfig,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.config.store import replace_config
from tonewatch.dsp.engine import EngineOutput
from tonewatch.dsp.matcher import Detection
from tonewatch.dsp.spectrum import SpectrumFrame
from tonewatch.events import EventBus, ToneDetected
from tonewatch.pipeline.channel import Channel
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.sources.base import AudioFrame


def _agency(**overrides: object) -> Agency:
    values: dict[str, object] = {
        "id": "north-unit",
        "name": "North Unit",
        "short_name": "NU",
        "kind": "rescue",
        "color": "#123456",
        "location": {"lat": 40.1, "lon": -105.1},
    }
    values.update(overrides)
    return Agency.model_validate(values)


def test_coverage_limits_and_ring_validation() -> None:
    ring = [[-105.1, 40.1], [-105.0, 40.1], [-105.0, 40.2], [-105.1, 40.1]]
    agency = _agency(
        coverage={"type": "Polygon", "coordinates": [ring]}, cad_names=["  North  ", "north"]
    )
    assert agency.cad_names == ["North"]
    with pytest.raises(ValidationError, match="closed"):
        _agency(coverage={"type": "Polygon", "coordinates": [ring[:-1]]})
    with pytest.raises(ValidationError, match="vertex"):
        _agency(coverage={"type": "Polygon", "coordinates": [[[-1, 0]] * 10001]})


def test_coordinates_and_tile_url_are_strict() -> None:
    with pytest.raises(ValidationError):
        AgencyLocation(lat=91, lon=0)
    with pytest.raises(ValidationError):
        MapConfig(tile_url="https://tiles.example/{z}/{x}/{y}.png?secret=x")
    for value in (
        "https://tiles.example/{z}/{x}/{y}.png;",
        "data:text/plain,x",
        "https://tiles.example/{z}/{x}",
        "https://{s}.tiles.example/{z}/{x}/{y}.png",
        "https://tiles.example:8443/{z}/{x}/{y}.png",
    ):
        with pytest.raises(ValidationError):
            MapConfig(tile_url=value)


def test_spa_csp_tile_origin_is_exact() -> None:
    empty = spa_csp()
    assert "https://" not in empty and empty.count("img-src 'self'") == 1
    configured = spa_csp(MapConfig(tile_url="https://tiles.example/{z}/{x}/{y}.png"))
    assert configured.count("https://tiles.example") == 1
    assert "https://other.example" not in configured


def test_default_https_port_is_removed_from_csp_origin() -> None:
    configured = spa_csp(MapConfig(tile_url="https://tiles.example:443/{z}/{x}/{y}.png"))
    assert configured == (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' https://tiles.example; media-src 'self'; "
        "font-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'self'; "
        "object-src 'none'"
    )


@pytest.mark.parametrize(
    "coverage",
    [
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-105.2, 40.1], [-105.0, 40.1], [-105.0, 40.2], [-105.2, 40.1]]],
                [[[-104.9, 40.1], [-104.8, 40.1], [-104.8, 40.2], [-104.9, 40.1]]],
            ],
        },
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-105.3, 40.0],
                    [-105.0, 40.0],
                    [-105.0, 40.3],
                    [-105.3, 40.3],
                    [-105.3, 40.0],
                ],
                [[-105.2, 40.1], [-105.1, 40.1], [-105.1, 40.2], [-105.2, 40.1]],
            ],
        },
    ],
)
def test_valid_multipolygon_and_polygon_hole_are_accepted(coverage: dict[str, object]) -> None:
    assert _agency(coverage=coverage).coverage == coverage


def test_invalid_multipolygon_and_coverage_size_are_rejected() -> None:
    invalid = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [0, 1]]]]}
    with pytest.raises(ValidationError, match="closed"):
        _agency(coverage=invalid)
    with pytest.raises(ValidationError, match="256 KiB"):
        _agency(coverage={"type": "Polygon", "coordinates": [], "notes": "x" * (256 * 1024)})


@pytest.mark.parametrize("value", [True, False, math.nan, math.inf, -math.inf])
def test_coverage_rejects_boolean_and_nonfinite_coordinates(value: object) -> None:
    with pytest.raises(ValidationError, match="positions"):
        _agency(
            coverage={
                "type": "Polygon",
                "coordinates": [[[value, 40], [0, 0], [0, 1], [value, 40]]],
            }
        )


@pytest.mark.asyncio
async def test_geojson_shape_and_geojson_identifier_route() -> None:
    agency = _agency(
        id="geojson",
        stations=[{"name": "Station A", "lat": 40.2, "lon": -105.2}],
        coverage={
            "type": "Polygon",
            "coordinates": [[[-105.2, 40.1], [-105.0, 40.1], [-105.0, 40.2], [-105.2, 40.1]]],
        },
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=AppConfig(agencies=[agency])))
    )
    payload = json.loads(bytes((await agencies_geojson(cast("Any", request))).body))
    assert len(payload["features"]) == 3
    assert payload["features"][0]["geometry"]["coordinates"] == [-105.1, 40.1]
    assert payload["features"][1]["properties"]["station_of"] == "geojson"
    assert sum(feature["geometry"]["type"] == "Polygon" for feature in payload["features"]) == 1
    assert (await get_agency(cast("Any", request), "geojson"))["id"] == "geojson"


@pytest.mark.asyncio
async def test_geojson_agency_without_stations_or_coverage_has_one_feature() -> None:
    agency = _agency(id="empty-agency")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=AppConfig(agencies=[agency])))
    )
    payload = json.loads(bytes((await agencies_geojson(cast("Any", request))).body))
    assert len(payload["features"]) == 1


def test_migration_0005_round_trip_keeps_existing_rows() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "migration.sqlite"
        _exercise_migration_round_trip(database)


def _exercise_migration_round_trip(database: Path) -> None:
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE calls (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, "
            "source_id TEXT NOT NULL, status TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE call_tone_sets (call_id TEXT NOT NULL, toneset_id TEXT NOT NULL, "
            "detected_at TEXT NOT NULL, matched_segment_freqs JSON NOT NULL, "
            "PRIMARY KEY (call_id, toneset_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO calls (id, started_at, source_id, status) VALUES (?, ?, ?, ?)",
            ("00000000-0000-0000-0000-000000000001", "2026-01-01 00:00:00", "radio", "closed"),
        )
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        revision = importlib.import_module(
            "tonewatch.storage.migrations.versions.0005_call_agency_snapshot"
        )
        with Operations.context(context):
            revision.upgrade()
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(call_tone_sets)")
        }
        assert {"agency_id", "agency_name", "agency_kind"} <= columns
        with Operations.context(context):
            revision.downgrade()
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(call_tone_sets)")
        }
        kept = connection.execute(text("SELECT count(*) FROM calls")).scalar_one()
        assert not {"agency_id", "agency_name", "agency_kind"} & columns
        assert kept == 1
        with Operations.context(context):
            revision.upgrade()
    engine.dispose()


def test_api_csp_docstring_is_the_security_contract() -> None:
    assert _set_api_csp.__doc__ == (
        "Deny all content for non-HTML API responses while forbidding foreign framing."
    )


def test_replace_config_preserves_every_untouched_field() -> None:
    current = AppConfig(
        discovery=DiscoveryConfig(
            enabled=False,
            clip=False,
            min_segment_s=0.4,
            max_segment_s=4,
            max_gap_s=0.7,
            tol_pct=2,
        ),
        map=MapConfig(tile_url="https://tiles.example/{z}/{x}/{y}.png", attribution="invented"),
    )
    updated = replace_config(current, tone_sets=[])
    assert updated.model_dump() == current.model_dump()


def test_dispatch_payload_agency_has_exact_shape_and_supports_null() -> None:
    call_id = uuid4()
    agency = {
        "id": "north-unit",
        "name": "North Unit",
        "short_name": "NU",
        "kind": "rescue",
        "lat": 40.1,
        "lon": -105.1,
    }
    state = {"tone_sets": ["page"], "source_id": "radio", "agency": agency}
    payload = AlertDispatcher._payload(call_id, "pre_alert", state, False, datetime.now(UTC))
    assert set(cast("dict[str, object]", payload["agency"])) == {
        "id",
        "name",
        "short_name",
        "kind",
        "lat",
        "lon",
    }
    assert (
        AlertDispatcher._payload(call_id, "closed", {"tone_sets": [], "agency": None}, False, None)[
            "agency"
        ]
        is None
    )


@pytest.mark.asyncio
async def test_channel_resolves_current_agency_at_detection_time() -> None:
    agency = _agency()
    current = {agency.id: agency}
    channel = Channel(
        FileSource(id="radio", name="radio", path="unused.wav"),
        [
            ToneSet(
                id="page",
                name="Page",
                agency_id=agency.id,
                sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
            )
        ],
        EventBus(),
        agency_lookup=lambda item_id: (
            current[item_id].model_dump(mode="json") if item_id in current else None
        ),
    )
    channel._anchor_wall = datetime.now(UTC)
    subscription = channel.bus.subscribe()
    await channel._publish_detection(Detection("page", 1, (), True))
    await __import__("asyncio").sleep(0)
    first = subscription.queue.get_nowait()
    assert isinstance(first, ToneDetected)
    current[agency.id] = agency.model_copy(update={"name": "Renamed Unit"})
    await channel._publish_detection(Detection("page", 2, (), True))
    await __import__("asyncio").sleep(0)
    second = subscription.queue.get_nowait()
    assert isinstance(second, ToneDetected)
    assert second.agency is not None
    assert second.agency["name"] == "Renamed Unit"


@pytest.mark.asyncio
async def test_dispatcher_uses_current_config_over_event_snapshot() -> None:
    old = _agency(name="Old Unit")
    new = old.model_copy(update={"name": "New Unit"})
    tone = ToneSet(
        id="page",
        name="Page",
        agency_id=old.id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
    )
    dispatcher = AlertDispatcher(AppConfig(tone_sets=[tone], agencies=[new]), EventBus())
    call_id = uuid4()
    await dispatcher.handle(
        ToneDetected(
            call_id,
            "page",
            datetime.now(UTC),
            "radio",
            agency={"id": old.id, "name": old.name},
        )
    )
    assert dispatcher._calls[call_id]["agency"]["name"] == "New Unit"


@pytest.mark.asyncio
async def test_event_payload_agency_survives_mqtt_and_webhook_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mqtt_payloads: list[dict[str, object]] = []
    webhook_payloads: list[dict[str, object]] = []

    class Publisher:
        async def publish_call(self, payload: dict[str, object]) -> None:
            mqtt_payloads.append(json.loads(json.dumps(payload)))

    async def fake_webhook(*args: object, **_kwargs: object) -> object:
        webhook_payloads.append(json.loads(json.dumps(args[1])))
        return SimpleNamespace(ok=True)

    monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", fake_webhook)
    dispatcher = AlertDispatcher(AppConfig(), EventBus())
    dispatcher._mqtt["mqtt"] = cast("Any", Publisher())
    agency = {
        "id": "north-unit",
        "name": "North Unit",
        "short_name": "NU",
        "kind": "rescue",
        "lat": 40.1,
        "lon": -105.1,
    }
    payload = dispatcher._payload(
        uuid4(), "pre_alert", {"tone_sets": ["page"], "agency": agency}, False, datetime.now(UTC)
    )
    await dispatcher._send(MqttTarget(id="mqtt", name="MQTT"), payload)
    await dispatcher._send(
        WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test")), payload
    )
    assert mqtt_payloads[0]["agency"] == agency
    assert webhook_payloads[0]["agency"] == agency
    null_payload = dispatcher._payload(
        uuid4(), "closed", {"tone_sets": [], "agency": None}, False, None
    )
    await dispatcher._send(MqttTarget(id="mqtt", name="MQTT"), null_payload)
    await dispatcher._send(
        WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.test")), null_payload
    )
    assert mqtt_payloads[1]["agency"] is None
    assert webhook_payloads[1]["agency"] is None


@pytest.mark.asyncio
async def test_ha_event_entity_uses_agency_bearing_call_topic() -> None:
    messages: list[tuple[str, object]] = []

    class Publisher:
        availability_topic = "tonewatch/instance/availability"

        async def publish(self, topic: str, payload: object, *, retain: bool = False) -> None:
            del retain
            messages.append((topic, payload))

    agency = _agency()
    tone = ToneSet(
        id="page",
        name="Page",
        agency_id=agency.id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
    )
    await HADiscovery(Publisher(), "instance").publish(
        AppConfig(tone_sets=[tone], agencies=[agency])
    )
    event_payload = next(
        json.loads(payload)
        for topic, payload in messages
        if "/event/" in topic and isinstance(payload, str)
    )
    assert event_payload["event_topic"] == "tonewatch/instance/call"


@pytest.mark.asyncio
async def test_supervisor_agency_only_reload_keeps_channel_and_updates_payload() -> None:
    source = FileSource(id="radio", name="Radio", path="invented.wav")
    agency = _agency()
    tone = ToneSet(
        id="page",
        name="Page",
        agency_id=agency.id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
    )
    config = AppConfig(sources=[source], tone_sets=[tone], agencies=[agency])

    class FakeChannel:
        def __init__(self, **kwargs: object) -> None:
            self.agency_lookup = kwargs["agency_lookup"]
            self.finished = asyncio.Event()

        async def run(self) -> None:
            await self.finished.wait()

    channels: list[FakeChannel] = []

    def factory(*_args: object, **kwargs: object) -> FakeChannel:
        channel = FakeChannel(**kwargs)
        channels.append(channel)
        return channel

    supervisor = Supervisor(config, EventBus(), None, channel_factory=cast("Any", factory))
    bus_subscription = supervisor.bus.subscribe(ToneDetected)
    await supervisor.start()
    await asyncio.sleep(0)
    task = supervisor._tasks["radio"]
    renamed = agency.model_copy(update={"name": "Renamed Unit"})
    await supervisor.reload(replace_config(config, agencies=[renamed]))
    assert supervisor._tasks["radio"] is task
    assert len(channels) == 1
    lookup = channels[0].agency_lookup
    assert callable(lookup)
    assert lookup("north-unit")["name"] == "Renamed Unit"
    supervisor.bus.publish(
        ToneDetected(uuid4(), "page", datetime.now(UTC), "radio", agency=lookup("north-unit"))
    )
    bus_event = await bus_subscription.__anext__()
    assert isinstance(bus_event, ToneDetected)
    assert bus_event.agency is not None
    assert bus_event.agency["name"] == "Renamed Unit"
    await supervisor.alerts.handle(
        ToneDetected(uuid4(), "page", datetime.now(UTC), "radio", agency={"name": "Old Unit"})
    )
    call = next(iter(supervisor.alerts._calls.values()))
    assert call["agency"]["name"] == "Renamed Unit"
    supervisor.bus.unsubscribe(bus_subscription)
    channels[0].finished.set()
    await supervisor.stop()


@pytest.mark.asyncio
async def test_channel_agency_squelch_and_live_gate_preserve_detection_time() -> None:
    agency = _agency()
    tone = ToneSet(
        id="page",
        name="Page",
        agency_id=agency.id,
        sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
    )
    source = FileSource(
        id="radio",
        name="Radio",
        path="invented.wav",
        squelch=SquelchConfig(mode="level", open_dbfs=-40, close_dbfs=-45),
    )
    frames = (
        SpectrumFrame(0.0, 1000, -30, 0.9, True),
        SpectrumFrame(1.0, 1000, -60, 0.9, True),
    )
    detection = Detection("page", 1.25, (), True)
    outputs = (
        EngineOutput((frames[0],), (), (detection,)),
        EngineOutput((frames[1],), (), ()),
    )

    class Source:
        async def open(self) -> None:
            pass

        async def close(self) -> None:
            pass

        def __aiter__(self) -> Any:
            async def stream() -> Any:
                for stream_time_s in (0.0, 1.0):
                    yield AudioFrame(np.zeros(160, dtype=np.float32), stream_time_s, "radio")

            return stream()

    class Engine:
        def __init__(self, _tonesets: list[ToneSet]) -> None:
            self.index = 0

        def feed(self, _samples: Any) -> EngineOutput:
            output = outputs[min(self.index, len(outputs) - 1)]
            self.index += 1
            return output

    def make_engine(_tonesets: list[ToneSet]) -> Engine:
        return Engine(_tonesets)

    def make_source(_config: Any) -> Source:
        return Source()

    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    gates: list[bool] = []

    class LiveHub:
        def feed(self, _source_id: str, _samples: Any, *, gate_open: bool = True) -> None:
            gates.append(gate_open)

    async def run(mode: Literal["off", "level"]) -> ToneDetected:
        config_source = source.model_copy(
            update={"squelch": SquelchConfig(mode=mode, attack_ms=0, hang_ms=0)}
        )
        bus = EventBus()
        subscription = bus.subscribe(ToneDetected)
        channel = Channel(
            config_source,
            [tone],
            bus,
            clock=lambda: fixed_now,
            source_factory=cast("Any", make_source),
            engine_factory=make_engine,
            live_hub=LiveHub(),
            agency_lookup=lambda agency_id: (
                {
                    "id": agency.id,
                    "name": agency.name,
                    "short_name": agency.short_name,
                    "kind": agency.kind,
                    "lat": agency.location.lat,
                    "lon": agency.location.lon,
                }
                if agency_id == agency.id
                else None
            ),
        )
        await channel.run()
        event = await subscription.__anext__()
        assert isinstance(event, ToneDetected)
        return event

    level_event = await run("level")
    off_event = await run("off")
    assert level_event.agency == {
        "id": agency.id,
        "name": agency.name,
        "short_name": agency.short_name,
        "kind": agency.kind,
        "lat": agency.location.lat,
        "lon": agency.location.lon,
    }
    assert level_event.detected_at == off_event.detected_at == fixed_now + timedelta(seconds=1.25)
    assert gates == [True, False, True, True]
