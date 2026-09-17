"""M17a contract tests (A/C)."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import AnyUrl
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL

import tonewatch.api.routes.admin as admin_routes
import tonewatch.api.routes.cad as cad_routes
from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.meshtastic import render_message
from tonewatch.alerts.webhook import WebhookResult
from tonewatch.api.routes.ws import serialize_event
from tonewatch.cad.correlate import (
    CadCorrelationService,
    CorrelationCall,
    CorrelationIncident,
    choose_incident,
)
from tonewatch.cad.feed import CadEvent, CadFeedRunner, CadSnapshot, parse_message
from tonewatch.config.models import (
    Agency,
    AgencyLocation,
    AlertTarget,
    AppConfig,
    CadFeed,
    MeshtasticTarget,
    MqttTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.events import CallEnriched, EventBus, ToneDetected
from tonewatch.recording.retention import RetentionPolicy, RetentionService
from tonewatch.storage.models import (
    Base,
    CadIncident,
    Call,
    CallCadIncident,
    CallToneSet,
    create_database,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return _Result(self.rows)


def _request(rows):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=AppConfig(),
                session_factory=lambda: _Session(rows),
            )
        ),
        state=SimpleNamespace(auth="test"),
    )


def test_m17_g_unmatched_agency_list_and_not_found_create():
    assert awaitable_unmatched(_request([("north", "North Unit", 2, None)]))[0]["count"] == 2
    with pytest.raises(HTTPException, match="unmatched agency"):
        asyncio.run(cad_routes.create_agency(_request([]), "missing"))


def awaitable_unmatched(request):
    return asyncio.run(cad_routes.unmatched(request))


def _incident(i="abcdef12", agency="North Unit", when="2026-01-01T00:00:00+00:00"):
    return {
        "id": i,
        "agency": {"name": agency, "key": agency},
        "received_at": when,
        "type": {"raw": "Medical", "key": "medical"},
    }


def test_m17_a_validation_rejects_oversize_wrong_schema_and_bad_id_without_raising():
    assert parse_message(b"x" * (1024 * 1024 + 1), "911/cad/incidents") == "payload exceeds 1 MiB"
    for item in (
        {"schema": 2},
        {"schema": 1, "event": "new", "incident": _incident("bad")},
    ):
        assert isinstance(parse_message(json.dumps(item), "911/cad/incident"), str)


def test_m17_a_rejected_payload_does_not_log_incident_fields(caplog):
    payload = {
        "schema": 2,
        "address_clean": "SECRET FICTIONAL ADDRESS",
        "type": {"raw": "SECRET TYPE"},
    }
    assert isinstance(
        parse_message(json.dumps(payload), "911/cad/incident", logger=logging.getLogger("cad")),
        str,
    )
    assert "SECRET FICTIONAL ADDRESS" not in caplog.text
    assert "SECRET TYPE" not in caplog.text


def test_m17_c_correlation_is_nearest_case_insensitive_and_edges_inclusive():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    call = CorrelationCall("call", start, ("NORTH UNIT",))
    assert (
        choose_incident(
            call, [CorrelationIncident("x", "north unit", start - timedelta(seconds=180))]
        ).id
        == "x"
    )
    assert choose_incident(call, [CorrelationIncident("x", "other", start)]) is None
    assert (
        choose_incident(
            call,
            [
                CorrelationIncident("far", "north unit", start + timedelta(seconds=50)),
                CorrelationIncident("near", "north unit", start - timedelta(seconds=5)),
            ],
        ).id
        == "near"
    )


def test_m17_ws_call_enriched_uses_lowercase_wire_event():
    event = CallEnriched(
        call_id=uuid4(),
        feed_id="county",
        incident_id="abcdef12",
        incident={"address_clean": "Fictional Avenue", "type": {"key": "medical"}},
        matched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert serialize_event(event)["type"] == "call_enriched"


def _snapshot(ids, fetched):
    return {
        "schema": 1,
        "fetched_at": fetched.isoformat(),
        "incidents": [_incident(item, when=fetched.isoformat()) for item in ids],
    }


@pytest.mark.asyncio
async def test_m17_b_snapshot_authority_and_restart_idempotence(tmp_path):
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'cad.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    runner = CadFeedRunner(
        CadFeed(id="county", name="County", host="127.0.0.1"),
        client_factory=lambda _feed: None,
        session_factory=sessions,
    )
    first = datetime(2026, 1, 1, tzinfo=UTC)
    await runner.persist(CadSnapshot.model_validate(_snapshot(["abcdef12", "abcdef13"], first)))
    await runner.persist(
        CadEvent.model_validate({"schema": 1, "event": "closed", "incident": _incident("abcdef13")})
    )
    await runner.persist(
        CadEvent.model_validate({"schema": 1, "event": "new", "incident": _incident("abcdef14")})
    )
    second = first + timedelta(minutes=1)
    snapshot = CadSnapshot.model_validate(_snapshot(["abcdef12", "abcdef14"], second))
    await runner.persist(snapshot)
    await runner.persist(snapshot)
    async with sessions() as session:
        rows = list(
            (await session.scalars(select(CadIncident).order_by(CadIncident.incident_id))).all()
        )
    assert [(row.incident_id, row.closed_at is None) for row in rows] == [
        ("abcdef12", True),
        ("abcdef13", False),
        ("abcdef14", True),
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_m17_g_create_unmatched_agency_audits(monkeypatch):
    row = SimpleNamespace(
        agency_key="north",
        agency_name="North Unit",
        agency_category="fire",
        last_seen_at=datetime.now(UTC),
    )
    request = _request([row])
    saved = []

    async def fake_save(_request, config):
        saved.append(config)
        return config

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cad_routes, "save_config", fake_save)
    monkeypatch.setattr(cad_routes, "record_audit", fake_audit)
    result = await cad_routes.create_agency(request, "north")
    assert result["cad_names"] == ["North Unit"]
    assert result["kind"] == "fire"
    assert saved


class _DisconnectClient:
    def __init__(self, disconnect: bool):
        self.disconnect = disconnect
        self.subscribed: list[tuple[str, int]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def subscribe(self, topic, qos):
        self.subscribed.append((topic, qos))

    @property
    def messages(self):
        async def stream():
            if self.disconnect:
                raise ConnectionError("disconnect")
            yield SimpleNamespace(payload=b"not-json", topic="911/cad/incident")
            await asyncio.Event().wait()
            yield None

        return stream()


@pytest.mark.asyncio
async def test_m17_h_runner_reconnects_with_backoff_and_cancels():
    clients = [_DisconnectClient(True), _DisconnectClient(False)]
    sleeps = []
    runner = CadFeedRunner(
        CadFeed(id="county", name="County", host="127.0.0.1"),
        client_factory=lambda _feed: clients.pop(0),
        sleep=lambda delay: sleeps.append(delay) or asyncio.sleep(0),
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    runner.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert sleeps


def test_m17_e_migration_0007_round_trip_keeps_calls(tmp_path: Path):
    database = tmp_path / "round-trip.sqlite"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "src" / "tonewatch" / "storage" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite", database=str(database)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "0006_alert_attempt_retry")
    call_id = uuid4().hex
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO calls (id, started_at, source_id, status) "
                "VALUES (:id, :started_at, :source_id, :status)"
            ),
            {
                "id": call_id,
                "started_at": datetime.now(UTC).isoformat(),
                "source_id": "cad-test",
                "status": "active",
            },
        )
    engine.dispose()
    command.upgrade(config, "0007_cad_incidents")
    command.downgrade(config, "0006_alert_attempt_retry")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM calls")).scalar_one() == 1
        assert "cad_incidents" in inspect(connection).get_table_names()
        assert "call_cad_incidents" in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.asyncio
async def test_m17_f_retention_deletes_unlinked_old_cad_and_cascades_links(tmp_path):
    now = datetime(2026, 4, 1, tzinfo=UTC)
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'retention.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    call_id = uuid4()
    async with sessions() as session:
        session.add(Call(id=call_id, started_at=now - timedelta(days=100), source_id="cad-test"))
        session.add_all(
            [
                CadIncident(
                    feed_id="county",
                    incident_id="abcdef12",
                    agency_name="North Unit",
                    agency_key="north",
                    type_raw="Medical",
                    type_key="medical",
                    address_clean="Fictional Avenue",
                    cross_streets=[],
                    municipality_raw="Fictional",
                    received_at=now - timedelta(days=100),
                    status="closed",
                    first_seen_at=now - timedelta(days=100),
                    last_seen_at=now - timedelta(days=100),
                ),
                CadIncident(
                    feed_id="county",
                    incident_id="abcdef13",
                    agency_name="North Unit",
                    agency_key="north",
                    type_raw="Medical",
                    type_key="medical",
                    address_clean="Fictional Road",
                    cross_streets=[],
                    municipality_raw="Fictional",
                    received_at=now - timedelta(days=100),
                    status="closed",
                    first_seen_at=now - timedelta(days=100),
                    last_seen_at=now - timedelta(days=100),
                ),
                CallCadIncident(
                    call_id=call_id,
                    feed_id="county",
                    incident_id="abcdef13",
                    matched_at=now - timedelta(days=100),
                    delta_s=1,
                ),
            ]
        )
        await session.commit()
        await RetentionService(
            tmp_path, RetentionPolicy(max_age_days=90), clock=now.timestamp
        ).enforce(session)
        assert (
            await session.scalar(
                select(CadIncident.incident_id).where(CadIncident.incident_id == "abcdef12")
            )
            is None
        )
        assert (
            await session.scalar(
                select(CadIncident.incident_id).where(CadIncident.incident_id == "abcdef13")
            )
            == "abcdef13"
        )
        await session.delete(await session.get(Call, call_id))
        await session.commit()
        assert (await session.scalar(select(CallCadIncident.call_id))) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_m17_health_cad_feed_section_reflects_feed_state():
    health = SimpleNamespace(
        connected=True,
        availability="online",
        last_message_at=datetime(2026, 1, 1, tzinfo=UTC),
        invalid_total=3,
        active_incidents=2,
    )

    class Scanner:
        async def scan(self):
            return {"recordings_bytes": 0, "free_bytes": 1, "db_bytes": 0, "db_wal_bytes": 0}

    class EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _query):
            return SimpleNamespace(all=lambda: [])

    config = AppConfig(cad_feeds=[CadFeed(id="county", name="County", host="127.0.0.1")])
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=config,
                supervisor=SimpleNamespace(cad_health={"county": health}, health={}, alerts=None),
                settings=SimpleNamespace(recording_path=".", data_dir=Path()),
                session_factory=EmptySession,
                bus=EventBus(),
                health_scanner=Scanner(),
            )
        )
    )
    result = await admin_routes.health(request)
    assert result["cad_feeds"] == [
        {
            "id": "county",
            "name": "County",
            "connected": True,
            "availability": "online",
            "last_message_at": health.last_message_at,
            "invalid_total": 3,
            "active_incidents": 2,
        }
    ]


def _correlation_config() -> AppConfig:
    agency = Agency(
        id="north",
        name="North Unit",
        short_name="North",
        kind="fire",
        color="#112233",
        location=AgencyLocation(lat=0, lon=0),
        cad_names=["North Unit"],
    )
    targets: list[AlertTarget] = [
        WebhookTarget(
            id="opt-in",
            name="Opt in",
            url=AnyUrl("https://example.test/opt-in"),
            events=["call_enriched"],
        ),
        WebhookTarget(
            id="opt-out",
            name="Opt out",
            url=AnyUrl("https://example.test/opt-out"),
            events=["pre_alert"],
        ),
    ]
    return AppConfig(
        agencies=[agency],
        tone_sets=[
            ToneSet(
                id="page",
                name="Page",
                agency_id="north",
                sequence=[ToneSpec(freq_hz=1000, min_s=0.1)],
                alert_targets=["opt-in", "opt-out"],
            )
        ],
        alert_targets=targets,
        cad_feeds=[CadFeed(id="county", name="County", host="127.0.0.1")],
    )


@pytest.mark.asyncio
async def test_m17_d_late_arrival_links_once_and_dispatches_only_opt_in(tmp_path, caplog):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    config = _correlation_config()
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'late.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    call_id = uuid4()
    async with sessions() as session:
        session.add(Call(id=call_id, started_at=start, source_id="radio"))
        session.add(
            CallToneSet(
                call_id=call_id,
                toneset_id="page",
                detected_at=start,
                matched_segment_freqs=[],
                agency_id="north",
                agency_name="North Unit",
                agency_kind="fire",
            )
        )
        await session.commit()
    bus = EventBus()
    service = CadCorrelationService(config, bus, sessions, clock=lambda: start)
    dispatcher = AlertDispatcher(config, bus, sessions, settings=SimpleNamespace())
    sent: list[dict[str, object]] = []
    send_done = asyncio.Event()

    async def fake_send(_target, payload, **_kwargs):
        sent.append(payload)
        send_done.set()
        return WebhookResult(True, status_code=204)

    dispatcher._send = fake_send
    await dispatcher.start()
    await dispatcher.handle(ToneDetected(call_id, "page", start, "radio", agency={"id": "north"}))
    sent.clear()
    events = bus.subscribe(CallEnriched)
    runner = CadFeedRunner(
        config.cad_feeds[0], client_factory=lambda _feed: None, session_factory=sessions
    )
    runner.on_incident = service.on_incident
    incident_at = start + timedelta(seconds=90)
    await runner.persist(
        CadEvent.model_validate(
            {
                "schema": 1,
                "event": "new",
                "incident": _incident(when=incident_at.isoformat()),
            }
        )
    )
    enriched = await asyncio.wait_for(events.__anext__(), 1)
    await asyncio.wait_for(send_done.wait(), 1)
    await runner.persist(
        CadEvent.model_validate(
            {
                "schema": 1,
                "event": "updated",
                "incident": _incident(when=incident_at.isoformat()),
            }
        )
    )
    await asyncio.sleep(0)
    async with sessions() as session:
        assert (
            len(
                (
                    await session.scalars(
                        select(CallCadIncident).where(CallCadIncident.call_id == call_id)
                    )
                ).all()
            )
            == 1
        )
    assert enriched.incident_id == "abcdef12"
    assert len(sent) == 1
    assert sent[0]["phase"] == "call_enriched"
    assert "Fictional Avenue" not in caplog.text
    assert "Medical" not in caplog.text
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(events.__anext__(), 0.01)
    bus.unsubscribe(events)
    await dispatcher.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_m17_d2_call_start_correlates_existing_only_in_window(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    config = _correlation_config()
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'start.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        incident = CadIncident(
            feed_id="county",
            incident_id="abcdef12",
            agency_name="North Unit",
            agency_key="north unit",
            type_raw="Medical",
            type_key="medical",
            address_clean="Fictional Avenue",
            cross_streets=[],
            municipality_raw="Fictional",
            received_at=start + timedelta(seconds=100),
            status="active",
            first_seen_at=start,
            last_seen_at=start,
        )
        session.add(incident)
        await session.commit()
    bus = EventBus()
    service = CadCorrelationService(config, bus, sessions, clock=lambda: start)
    events = bus.subscribe(CallEnriched)
    call_id = uuid4()
    async with sessions() as session:
        session.add(Call(id=call_id, started_at=start, source_id="radio"))
        session.add(
            CallToneSet(
                call_id=call_id,
                toneset_id="page",
                detected_at=start,
                matched_segment_freqs=[],
                agency_id="north",
                agency_name="North Unit",
                agency_kind="fire",
            )
        )
        await session.commit()
    await service.on_call_start(ToneDetected(call_id, "page", start, agency={"id": "north"}))
    enriched = await asyncio.wait_for(events.__anext__(), 1)
    assert enriched.call_id == call_id
    async with sessions() as session:
        assert await session.scalar(select(CallCadIncident.incident_id)) == "abcdef12"
        far_id = uuid4()
        session.add(Call(id=far_id, started_at=start + timedelta(seconds=1000), source_id="radio"))
        session.add(
            CallToneSet(
                call_id=far_id,
                toneset_id="page",
                detected_at=start + timedelta(seconds=1000),
                matched_segment_freqs=[],
                agency_id="north",
                agency_name="North Unit",
                agency_kind="fire",
            )
        )
        await session.commit()
    await service.on_call_start(
        ToneDetected(far_id, "page", start + timedelta(seconds=1000), agency={"id": "north"})
    )
    async with sessions() as session:
        assert (
            await session.scalar(
                select(CallCadIncident.incident_id).where(CallCadIncident.call_id == far_id)
            )
            is None
        )
    bus.unsubscribe(events)
    await engine.dispose()


def _mesh_target(
    template: str,
    *,
    phases: list[Literal["pre_alert", "recording_ready", "closed", "call_enriched"]],
    max_bytes: int = 200,
):
    return MeshtasticTarget(
        id="mesh",
        name="Mesh",
        host="127.0.0.1",
        gateway_node_id="!12345678",
        acknowledge_public_channel=True,
        template=template,
        phases=phases,
        max_bytes=max_bytes,
    )


def test_m17_i_meshtastic_cad_fields_are_opt_in_sanitized_and_truncated():
    payload = {
        "tone_sets": ["page"],
        "detected_at": "2026-01-01T00:00:00+00:00",
        "agency": {"name": "North"},
        "cad_type": "Medical https://secret.invalid/very-long-type",
        "cad_address": "Fictional Avenue " + "x" * 200,
    }
    default = render_message(
        _mesh_target("TONE {agency} {toneset}", phases=["call_enriched"]), payload
    )
    assert "Fictional Avenue" not in default
    rendered = render_message(
        _mesh_target("{cad_type} {cad_address}", phases=["call_enriched"], max_bytes=40), payload
    )
    assert "https" not in rendered
    assert "Fictional Avenue" in rendered
    assert len(rendered.encode()) <= 40


@pytest.mark.asyncio
async def test_m17_mqtt_call_enriched_payload_has_golden_keys():
    config = _correlation_config()
    dispatcher = AlertDispatcher(config, EventBus(), settings=SimpleNamespace())
    captured: list[dict[str, object]] = []

    class Publisher:
        async def publish_call(self, payload):
            captured.append(payload)

    dispatcher._mqtt["opt-in"] = Publisher()
    dispatcher._calls[uuid4()]["tone_sets"] = ["page"]
    call_id = next(iter(dispatcher._calls))
    target = next(item for item in config.alert_targets if item.id == "opt-in")
    dispatcher.config = AppConfig(
        agencies=config.agencies,
        tone_sets=[config.tone_sets[0].model_copy(update={"alert_targets": ["opt-in"]})],
        alert_targets=[MqttTarget(id=target.id, name=target.name, events=["call_enriched"])],
        cad_feeds=config.cad_feeds,
    )
    dispatcher._mqtt["opt-in"] = Publisher()
    await dispatcher.handle(
        CallEnriched(
            call_id=call_id,
            feed_id="county",
            incident_id="abcdef12",
            incident={
                "agency": {"name": "North Unit", "key": "north unit"},
                "type": {"raw": "Medical", "key": "medical", "code": None},
                "address_clean": "Fictional Avenue",
                "cross_streets": [],
                "municipality": {"raw": "Fictional", "name": "Fictional"},
                "received_at": "2026-01-01T00:01:30+00:00",
            },
            matched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    assert captured == [
        {
            "call_id": str(call_id),
            "tone_sets": ["page"],
            "phase": "call_enriched",
            "detected_at": None,
            "recording_url": None,
            "source_id": "",
            "test": False,
            "agency": {"name": "North Unit", "key": "north unit"},
            "recording_path_relative": True,
            "toneset": "page",
            "tone_set_names": ["Page"],
            "event": "call_enriched",
            "feed_id": "county",
            "incident_id": "abcdef12",
            "type": {"raw": "Medical", "key": "medical", "code": None},
            "cad_type": {"raw": "Medical", "key": "medical", "code": None},
            "address_clean": "Fictional Avenue",
            "cad_address": "Fictional Avenue",
            "cross_streets": [],
            "municipality": {"raw": "Fictional", "name": "Fictional"},
            "received_at": "2026-01-01T00:01:30+00:00",
        }
    ]


@pytest.mark.asyncio
async def test_m17_i_meshtastic_without_enrichment_phase_sends_nothing():
    config = _correlation_config()
    mesh = _mesh_target("{cad_type} {cad_address}", phases=["pre_alert"])
    config = AppConfig(
        agencies=config.agencies,
        tone_sets=[config.tone_sets[0].model_copy(update={"alert_targets": ["mesh"]})],
        alert_targets=[mesh],
        cad_feeds=config.cad_feeds,
    )
    dispatcher = AlertDispatcher(config, EventBus(), settings=SimpleNamespace())
    sent: list[dict[str, object]] = []

    class Sender:
        async def send(self, payload):
            sent.append(payload)
            return WebhookResult(True)

    dispatcher._meshtastic["mesh"] = Sender()
    call_id = uuid4()
    dispatcher._calls[call_id]["tone_sets"] = ["page"]
    await dispatcher.handle(
        CallEnriched(
            call_id=call_id,
            feed_id="county",
            incident_id="abcdef12",
            incident={"cad_type": "Medical", "address_clean": "Fictional Avenue"},
            matched_at=datetime.now(UTC),
        )
    )
    assert sent == []
