"""M18 Meshtastic target and sender contract tests."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import AnyUrl, ValidationError

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.meshtastic import MeshtasticSender, render_message, truncate_utf8
from tonewatch.api.audit import _SECRET_WORDS, is_secret_key, mask_secrets
from tonewatch.api.routes.config import test_alert_target as alert_target_test_route
from tonewatch.config.models import (
    Agency,
    AgencyLocation,
    AppConfig,
    MeshtasticTarget,
    MqttTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.events import CallClosed, EventBus, RecordingReady, RecordingStored, ToneDetected

if TYPE_CHECKING:
    from fastapi import Request


def target(**kwargs: object) -> MeshtasticTarget:
    values: dict[str, Any] = {
        "id": "mesh",
        "name": "Mesh",
        "host": "127.0.0.1",
        "gateway_node_id": "!9abc1234",
        "channel_index": 1,
    }
    values.update(kwargs)
    return MeshtasticTarget.model_validate(values)


def test_meshtastic_model_validates_nodes_public_channel_and_broker_reference() -> None:
    item = target(destination="!00000001")
    assert item.gateway_number == 0x9ABC1234
    assert item.destination_number == 1
    with pytest.raises(ValidationError, match="public channel"):
        MeshtasticTarget(id="mesh", name="Mesh", host="localhost", gateway_node_id="!9abc1234")
    with pytest.raises(ValidationError):
        target(gateway_node_id="9abc1234")
    with pytest.raises(ValidationError, match="exactly one"):
        target(mqtt_target_id="mqtt")
    ref = MeshtasticTarget(
        id="mesh", name="Mesh", mqtt_target_id="mqtt", gateway_node_id="!9abc1234", channel_index=1
    )
    config = AppConfig(alert_targets=[MqttTarget(id="mqtt", name="MQTT"), ref])
    assert cast("MeshtasticTarget", config.alert_targets[-1]).mqtt_target_id == "mqtt"
    with pytest.raises(ValidationError, match="missing MQTT target"):
        AppConfig(alert_targets=[ref])


@pytest.mark.parametrize("zone", ["America/Denver", "UTC"])
def test_meshtastic_timezone_accepts_iana_zones(zone: str) -> None:
    assert target(timezone=zone).timezone == zone


def test_meshtastic_timezone_rejects_unknown_zone() -> None:
    with pytest.raises(ValidationError, match="valid IANA"):
        target(timezone="Mars/Olympus")


def test_template_fields_and_urls_are_sanitized() -> None:
    item = target(template="{agency_short} {agency} {tonesets} {time} {source} {call_id_short}")
    rendered = render_message(
        item,
        {
            "tone_sets": ["Fire https://private.example/recording"],
            "source_id": "radio\nA",
            "call_id": "1234567890",
            "recording_url": "https://private.example/audio.mp3",
            "detected_at": "2026-09-12T12:34:00+00:00",
        },
    )
    assert "http" not in rendered.lower()
    assert "private.example" not in rendered
    assert "12345678" in rendered
    with pytest.raises(ValidationError, match="unsupported Meshtastic placeholder"):
        target(template="{cad_type}")
    with pytest.raises(ValidationError, match="http"):
        target(template="see http://example.invalid {time}")
    assert render_message(target(), {"tone_sets": ["Fire", "EMS"]}).startswith(
        "TONE Fire,EMS Fire,EMS "
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://home.example.zip/x",
        "10.1.0.5:8080/api/recordings/1.mp3",
        "[fe80::1]:8099/a",
        "ftp://files.example/a",
        "tonewatch.local/api",
    ],
)
def test_url_scrubbing_covers_non_common_hosts(url: str) -> None:
    rendered = render_message(target(template="{source}"), {"source_id": url})
    assert url not in rendered
    assert rendered == ""


def test_agency_dict_is_rendered_as_names() -> None:
    rendered = render_message(
        target(template="{agency_short}|{agency}|{tonesets}"),
        {
            "agency": {"id": "fd", "name": "Fire Department", "short_name": "FD"},
            "tone_sets": ["county-fire"],
            "tone_set_names": ["County Fire"],
        },
    )
    assert rendered == "FD|Fire Department|County Fire"


def test_sender_rate_limiter_is_per_sender() -> None:
    sender = MeshtasticSender(target(min_interval_s=30, max_per_hour=1))
    sender._last_sent = time.monotonic()
    sender._sent.append(time.monotonic())
    assert sender.rate_limited()


def test_secret_key_helper_matches_masking_word_list() -> None:
    for word in _SECRET_WORDS:
        key = f"prefix_{word}_suffix"
        assert is_secret_key(key)
        assert mask_secrets({key: "value"})[key] == "[REDACTED]"
    assert not is_secret_key("display_name")


@pytest.mark.asyncio
async def test_alert_target_test_route_marks_synthetic_delivery() -> None:
    class Alerts:
        async def test_target(self, _target_id: str) -> Any:
            return {"ok": True, "error": None}

    request = cast(
        "Request",
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=AppConfig(alert_targets=[target()]),
                    supervisor=SimpleNamespace(alerts=Alerts()),
                )
            )
        ),
    )
    assert await alert_target_test_route(request, "mesh") == {
        "ok": True,
        "error": None,
    }


@given(st.text(), st.integers(min_value=1, max_value=200))
def test_truncation_is_valid_utf8_and_bounded(value: str, max_bytes: int) -> None:
    result = truncate_utf8(value, max_bytes)
    assert len(result.encode()) <= max_bytes
    result.encode("utf-8")
    if len(value.encode()) > max_bytes:
        if result.endswith("…"):
            assert value.startswith(result[:-1])
        else:
            assert value.startswith(result)
    else:
        assert result == value


@pytest.mark.asyncio
async def test_sender_golden_payload_qos_and_retain(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[tuple[str, str, int, bool]] = []

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def publish(self, topic: str, payload: str, *, qos: int, retain: bool) -> None:
            published.append((topic, payload, qos, retain))

    monkeypatch.setattr("tonewatch.alerts.meshtastic.aiomqtt.Client", Client)
    result = await MeshtasticSender(target()).send(
        {
            "tone_sets": ["Fire"],
            "source_id": "radio",
            "call_id": "12345678",
            "detected_at": "2026-09-12T12:34:00+00:00",
        }
    )
    assert result.ok
    topic, raw, qos, retain = published[0]
    assert topic == "msh/US/2/json/mqtt/"
    assert (qos, retain) == (1, False)
    expected_time = (
        datetime.fromisoformat("2026-09-12T12:34:00+00:00").astimezone(UTC).strftime("%H:%M")
    )
    assert json.loads(raw) == {
        "from": 0x9ABC1234,
        "to": 0xFFFFFFFF,
        "channel": 1,
        "type": "sendtext",
        "payload": f"TONE Fire Fire {expected_time}",
    }


@pytest.mark.asyncio
async def test_dispatcher_coalesces_stacked_tones_without_delaying_other_targets() -> None:
    release = asyncio.Event()
    waits: list[float] = []
    sent: list[dict[str, object]] = []

    async def sleep(delay: float) -> None:
        waits.append(delay)
        await release.wait()

    config = AppConfig(
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=["mesh"],
            ),
            ToneSet(
                id="city-ems",
                name="City EMS",
                sequence=[ToneSpec(freq_hz=1100, min_s=1)],
                alert_targets=["mesh"],
            ),
        ],
        alert_targets=[target(id="mesh", coalesce_s=3)],
    )
    dispatcher = AlertDispatcher(config, EventBus(), settings=SimpleNamespace(), sleep=sleep)

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            sent.append(payload)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await dispatcher.handle(ToneDetected(call_id, "city-ems", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    assert waits == [3]
    assert sent == []
    release.set()
    await asyncio.sleep(0)
    assert len(sent) == 1
    assert sent[0]["tone_set_names"] == ["County Fire", "City EMS"]


def _mesh_dispatcher(
    target_item: MeshtasticTarget,
    rows: list[object] | None = None,
    sleep: Any = asyncio.sleep,
) -> AlertDispatcher:
    config = AppConfig(
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=[target_item.id],
            )
        ],
        alert_targets=[target_item],
    )

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def add(self, row: object) -> None:
            if rows is not None:
                rows.append(row)

        async def commit(self) -> None:
            return None

    session_factory = Session if rows is not None else None
    return AlertDispatcher(
        config,
        EventBus(),
        session_factory,
        settings=SimpleNamespace(),
        sleep=sleep,
    )


@pytest.mark.asyncio
async def test_dispatcher_sends_one_follow_up_after_coalescing_window() -> None:
    target_item = target(coalesce_s=0, min_interval_s=0, max_per_hour=20)
    dispatcher = _mesh_dispatcher(target_item)
    sent: list[dict[str, object]] = []

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            sent.append(payload)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_dispatcher_race_during_first_send_produces_one_follow_up() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    sent: list[dict[str, object]] = []
    target_item = target(coalesce_s=0, min_interval_s=0)
    dispatcher = AlertDispatcher(
        AppConfig(
            tone_sets=[
                ToneSet(
                    id="county-fire",
                    name="County Fire",
                    sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                    alert_targets=[target_item.id],
                ),
                ToneSet(
                    id="city-ems",
                    name="City EMS",
                    sequence=[ToneSpec(freq_hz=1100, min_s=1)],
                    alert_targets=[target_item.id],
                ),
            ],
            alert_targets=[target_item],
        ),
        EventBus(),
        settings=SimpleNamespace(),
    )

    class Sender:
        count = 0

        async def send(self, payload: dict[str, object]) -> Any:
            self.count += 1
            sent.append(payload)
            if self.count == 1:
                entered.set()
                await release.wait()
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await entered.wait()
    follow_up = asyncio.create_task(
        dispatcher.handle(ToneDetected(call_id, "city-ems", datetime.now(UTC), "radio"))
    )
    release.set()
    await follow_up
    for _ in range(3):
        await asyncio.sleep(0)
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_dispatcher_follow_up_rate_limit_is_recorded_once() -> None:
    rows: list[object] = []
    target_item = target(coalesce_s=0, min_interval_s=30, max_per_hour=20)
    dispatcher = _mesh_dispatcher(target_item, rows)

    class Sender:
        count = 0

        async def send(self, _payload: dict[str, object]) -> Any:
            self.count += 1
            return SimpleNamespace(
                ok=self.count == 1,
                error=None if self.count == 1 else "rate_limited",
                status_code=0,
            )

    sender = Sender()
    dispatcher._meshtastic["mesh"] = cast("Any", sender)
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    assert sender.count == 2
    assert [getattr(row, "error", None) for row in rows] == [None, "rate_limited"]


@pytest.mark.asyncio
async def test_dispatcher_prunes_mesh_state_when_calls_close() -> None:
    target_item = target(coalesce_s=0)
    dispatcher = _mesh_dispatcher(target_item)

    class Sender:
        async def send(self, _payload: dict[str, object]) -> Any:
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    for _ in range(1000):
        call_id = uuid4()
        await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
        await asyncio.sleep(0)
        await dispatcher.handle(CallClosed(call_id, "closed", "radio"))
    assert not dispatcher._mesh_sent
    assert not dispatcher._calls


@pytest.mark.asyncio
async def test_dispatcher_reload_cancels_removed_mesh_coalescing_task() -> None:
    release = asyncio.Event()

    async def sleep(_delay: float) -> None:
        await release.wait()

    target_item = target(coalesce_s=3)
    dispatcher = _mesh_dispatcher(target_item, sleep=sleep)
    sender = SimpleNamespace(send=lambda _payload: None)
    dispatcher._meshtastic["mesh"] = cast("Any", sender)
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await asyncio.sleep(0)
    dispatcher.task = cast("Any", asyncio.current_task())
    await dispatcher.reload(AppConfig())
    release.set()
    assert not dispatcher._coalescing


def test_dispatcher_payload_urls_never_reach_meshtastic_message() -> None:
    rendered = render_message(
        target(template="{source}"),
        {
            "source_id": "radio https://example.local/live.mp3?token=secret",
            "recording_url": "https://example.local/api/recordings/1",
        },
    )
    assert "example.local" not in rendered
    assert "secret" not in rendered


def test_agency_absent_and_none_fall_back_without_repr() -> None:
    item = target(template="{agency_short}|{agency}")
    for payload in ({"agency": None}, {}):
        rendered = render_message(
            item,
            {**payload, "tone_sets": ["county-fire"], "tone_set_names": ["County Fire"]},
        )
        assert rendered == "County Fire|County Fire"
        assert not any(value in rendered for value in ("{", "[", "'id'"))


def test_meshtastic_timezone_precedence_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    zones = {
        "America/New_York": timezone(-timedelta(hours=5)),
        "Europe/Berlin": timezone(timedelta(hours=1)),
    }
    monkeypatch.setattr("tonewatch.alerts.meshtastic._timezone", lambda name: zones.get(name, UTC))
    payload: dict[str, object] = {
        "detected_at": "2026-01-15T12:00:00+00:00",
        "tone_sets": ["county-fire"],
    }
    ny_values = target().model_dump()
    ny_values["timezone"] = "America/New_York"
    ny = MeshtasticTarget.model_construct(**ny_values)
    assert render_message(ny, payload).endswith("07:00")
    berlin = target()
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert render_message(berlin, payload).endswith("13:00")
    monkeypatch.delenv("TZ")
    assert render_message(berlin, payload).endswith("12:00")
    with pytest.raises(ValidationError, match="valid IANA"):
        target(timezone="Invalid/Not-A-Zone")


@pytest.mark.parametrize(
    ("detected_at", "expected"),
    [
        ("2026-01-15T12:00:00+00:00", "05:00"),
        ("2026-07-15T12:00:00+00:00", "06:00"),
    ],
)
def test_meshtastic_timezone_renders_fixed_utc_timestamp(detected_at: str, expected: str) -> None:
    item = target(timezone="America/Denver")
    rendered = render_message(item, {"detected_at": detected_at})
    assert rendered.endswith(expected)


@pytest.mark.asyncio
async def test_stacked_agencies_render_unique_names_without_repr() -> None:
    agencies = [
        Agency(
            id="alpha-fire",
            name="Alpha Fire",
            short_name="AFD",
            kind="fire",
            color="#112233",
            location=AgencyLocation(lat=40, lon=-105),
        ),
        Agency(
            id="bravo-ems",
            name="Bravo EMS",
            short_name="BEMS",
            kind="ems",
            color="#223344",
            location=AgencyLocation(lat=41, lon=-104),
        ),
    ]
    config = AppConfig(
        agencies=agencies,
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                agency_id="alpha-fire",
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=["mesh"],
            ),
            ToneSet(
                id="city-ems",
                name="City EMS",
                agency_id="bravo-ems",
                sequence=[ToneSpec(freq_hz=1100, min_s=1)],
                alert_targets=["mesh"],
            ),
        ],
        alert_targets=[target(coalesce_s=0, template="{agency_short}|{agency}")],
    )
    dispatcher = AlertDispatcher(
        config, EventBus(), settings=SimpleNamespace(), sleep=asyncio.sleep
    )
    sent: list[dict[str, object]] = []

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            sent.append(payload)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    call_id = uuid4()
    now = datetime.now(UTC)
    await dispatcher.handle(ToneDetected(call_id, "county-fire", now, "radio"))
    await dispatcher.handle(ToneDetected(call_id, "city-ems", now, "radio"))
    for _ in range(3):
        await asyncio.sleep(0)
    rendered = render_message(cast("MeshtasticTarget", config.alert_targets[0]), sent[0])
    assert rendered == "AFD/BEMS|Alpha Fire/Bravo EMS"
    assert not any(value in rendered for value in ("{", "[", "'id'"))


@pytest.mark.asyncio
async def test_agency_rename_during_coalescing_reloads_for_mesh_and_mqtt() -> None:
    release = asyncio.Event()
    agency = Agency(
        id="alpha-fire",
        name="Old Fire",
        short_name="OLD",
        kind="fire",
        color="#112233",
        location=AgencyLocation(lat=40, lon=-105),
    )
    mesh = target(coalesce_s=3, template="{agency_short}")
    mqtt = MqttTarget(id="mqtt", name="MQTT")
    config = AppConfig(
        agencies=[agency],
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                agency_id=agency.id,
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=[mesh.id],
            )
        ],
        alert_targets=[mesh, mqtt],
    )

    async def sleep(_delay: float) -> None:
        await release.wait()

    dispatcher = AlertDispatcher(config, EventBus(), settings=SimpleNamespace(), sleep=sleep)
    mesh_sent: list[dict[str, object]] = []
    mqtt_sent: list[dict[str, object]] = []

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            mesh_sent.append(payload)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    class Publisher:
        async def publish_call(self, payload: dict[str, object]) -> None:
            mqtt_sent.append(payload)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    dispatcher._mqtt["mqtt"] = cast("Any", Publisher())
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    renamed = agency.model_copy(update={"name": "New Fire", "short_name": "NEW"})
    reloaded_tone = config.tone_sets[0].model_copy(update={"alert_targets": [mesh.id, mqtt.id]})
    await dispatcher.reload(
        config.model_copy(update={"agencies": [renamed], "tone_sets": [reloaded_tone]})
    )
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    release.set()
    for _ in range(3):
        await asyncio.sleep(0)
    assert render_message(mesh, mesh_sent[0]) == "NEW"
    assert mqtt_sent[0]["agency"] == {
        "id": "alpha-fire",
        "name": "New Fire",
        "short_name": "NEW",
        "kind": "fire",
        "lat": 40.0,
        "lon": -105.0,
    }


@pytest.mark.asyncio
async def test_recording_stored_after_close_keeps_dispatcher_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []

    async def send_webhook(
        _target: WebhookTarget,
        payload: dict[str, object],
        *_args: object,
        **_kwargs: object,
    ) -> Any:
        sent.append(payload)
        return SimpleNamespace(ok=True, error=None, status_code=200)

    monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", send_webhook)
    hook = WebhookTarget(id="hook", name="Hook", url=AnyUrl("https://example.com"))
    config = AppConfig(
        tone_sets=[
            ToneSet(
                id="county-fire",
                name="County Fire",
                sequence=[ToneSpec(freq_hz=1000, min_s=1)],
                alert_targets=["hook"],
            )
        ],
        alert_targets=[hook],
    )
    dispatcher = AlertDispatcher(config, EventBus(), settings=SimpleNamespace())
    call_id = uuid4()
    detected = datetime.now(UTC)
    await dispatcher.handle(ToneDetected(call_id, "county-fire", detected, "radio"))
    await dispatcher.handle(RecordingReady(call_id, "call.mp3", "mp3", "radio"))
    await dispatcher.handle(CallClosed(call_id, "closed", "radio"))
    await dispatcher.handle(RecordingStored(call_id, 1, "mp3", "radio"))
    assert [payload["phase"] for payload in sent] == [
        "pre_alert",
        "closed",
        "recording_ready",
    ]
    assert call_id not in dispatcher._calls


@pytest.mark.asyncio
async def test_meshtastic_phases_do_not_coalesce_recording_ready() -> None:
    calls: list[dict[str, object]] = []
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    target_item = target(phases=["recording_ready"], coalesce_s=3)
    dispatcher = _mesh_dispatcher(target_item, sleep=sleep)

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            calls.append(payload)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    call_id = uuid4()
    await dispatcher.handle(ToneDetected(call_id, "county-fire", datetime.now(UTC), "radio"))
    await dispatcher.handle(RecordingStored(call_id, 1, "mp3", "radio"))
    assert [payload["phase"] for payload in calls] == ["recording_ready"]
    assert delays == []


@pytest.mark.asyncio
async def test_meshtastic_template_reload_applies_to_next_call() -> None:
    calls: list[str] = []
    target_item = target(coalesce_s=0, min_interval_s=0)
    dispatcher = _mesh_dispatcher(target_item)

    class Sender:
        async def send(self, payload: dict[str, object]) -> Any:
            calls.append(
                render_message(
                    cast("MeshtasticTarget", dispatcher.config.alert_targets[0]), payload
                )
            )
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    await dispatcher.handle(ToneDetected(uuid4(), "county-fire", datetime.now(UTC), "radio"))
    for _ in range(3):
        await asyncio.sleep(0)
    reloaded = AppConfig(
        tone_sets=dispatcher.config.tone_sets,
        alert_targets=[target(coalesce_s=0, min_interval_s=0, template="NEW {toneset}")],
    )
    await dispatcher.reload(reloaded)
    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    await dispatcher.handle(ToneDetected(uuid4(), "county-fire", datetime.now(UTC), "radio"))
    for _ in range(3):
        await asyncio.sleep(0)
    assert calls[-1] == "NEW county-fire"


@pytest.mark.asyncio
async def test_alert_target_test_uses_target_timeout_and_returns_error() -> None:
    target_item = target(timeout_s=0.01)
    dispatcher = _mesh_dispatcher(target_item)

    class Sender:
        async def send(self, _payload: dict[str, object]) -> Any:
            await asyncio.sleep(1)
            return SimpleNamespace(ok=True, error=None, status_code=0)

    dispatcher._meshtastic["mesh"] = cast("Any", Sender())
    assert await dispatcher.test_target("mesh") == {"ok": False, "error": "target timeout"}
