"""M7 alert, SSRF, webhook, and script evidence tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import AnyUrl

from tonewatch.alerts.dispatcher import AlertDispatcher
from tonewatch.alerts.ha_discovery import HADiscovery
from tonewatch.alerts.mqtt import MqttPublisher, addon_mqtt_credentials
from tonewatch.alerts.script import argv_for, resolve_executable, run_script
from tonewatch.alerts.urlsafety import (
    PinnedIPTransport,
    ResolvedURL,
    UnsafeURL,
    is_blocked_address,
    parse_ip,
    resolve_and_validate,
    validate_url,
)
from tonewatch.alerts.webhook import send_webhook, signature
from tonewatch.config.models import (
    AppConfig,
    FileSource,
    MqttTarget,
    ScriptTarget,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.events import CallClosed, EventBus, RecordingReady, ToneDetected
from tonewatch.settings import Settings

# Resolved once: on Linux uv venvs sys.executable is a symlink, and resolve_executable()
# follows symlinks, so allowlists must name the real interpreter directory.
PYTHON = Path(sys.executable).resolve()


def tone_set(*targets: str) -> ToneSet:
    return ToneSet(
        id="page",
        name="Page",
        sequence=[ToneSpec(freq_hz=1000, min_s=1)],
        alert_targets=list(targets),
    )


def _resolver(_host: str, _port: int | None, **_kwargs: object) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("192.168.1.20", 0))]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://2130706433/",
        "http://0x7f.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1]/",
        "http://0.0.0.0/",
    ],
)
def test_urlsafety_blocks_loopback_linklocal_metadata_and_encodings(url: str) -> None:
    with pytest.raises(UnsafeURL):
        validate_url(url, schemes=frozenset({"http"}))


def test_urlsafety_allows_private_lan_by_default_and_blocks_when_configured() -> None:
    assert validate_url("http://192.168.1.20/", schemes=frozenset({"http"})).host
    with pytest.raises(UnsafeURL):
        validate_url("http://192.168.1.20/", schemes=frozenset({"http"}), allow_private=False)
    assert is_blocked_address(__import__("ipaddress").ip_address("10.0.0.1"), block_private=True)


def test_urlsafety_parses_legacy_forms_and_validates_resolved_public_address() -> None:
    assert str(parse_ip("127.1")) == "127.0.0.1"
    assert str(parse_ip("127.0.1.1")) == "127.0.1.1"
    assert str(parse_ip("0x7f000001")) == "127.0.0.1"
    assert parse_ip("1.2.3.4.5") is None
    assert parse_ip("1..2") is None
    assert parse_ip("0x") is None
    assert str(parse_ip("2130706433")) == "127.0.0.1"
    assert str(parse_ip("0x7f.1")) == "127.0.0.1"
    assert parse_ip("1.2.3.999") is None

    async def run() -> None:
        resolved = await resolve_and_validate(
            "https://radio.local/",
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 0))],
        )
        assert str(resolved.address) == "8.8.8.8"
        with pytest.raises(UnsafeURL):
            await resolve_and_validate(
                "https://radio.local/",
                resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
            )

    asyncio.run(run())


def test_urlsafety_pinned_transport_preserves_host_and_sni() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204, request=request)

        resolved = ResolvedURL(
            httpx.URL("https://radio.local/path"), ipaddress.ip_address("8.8.8.8")
        )
        transport = PinnedIPTransport(resolved, httpx.MockTransport(handler))
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get("https://radio.local/path")
        assert response.status_code == 204
        assert seen[0].url.host == "8.8.8.8"
        assert seen[0].headers["host"] == "radio.local"
        assert seen[0].extensions["sni_hostname"] == "radio.local"

    asyncio.run(run())


def _webhook_factory(seen: list[httpx.Request], response_factory: Any | None = None) -> Any:
    def factory(**_kwargs: object) -> httpx.AsyncClient:
        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            response = response_factory(request) if response_factory else httpx.Response(200)
            return response

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


def test_webhook_pins_resolved_ip_against_dns_rebinding() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []
        target = WebhookTarget(
            id="hook", name="Hook", url=AnyUrl("http://radio.local/"), allow_insecure_http=True
        )
        result = await send_webhook(
            target,
            {"call_id": "c"},
            Settings(),
            resolver=_resolver,
            client_factory=_webhook_factory(seen),
        )
        assert result.ok
        assert seen[0].url.host == "192.168.1.20"
        assert seen[0].headers["host"] == "radio.local"

    asyncio.run(run())


def test_webhook_does_not_follow_redirects() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []

        def redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"}, request=request)

        target = WebhookTarget(
            id="hook", name="Hook", url=AnyUrl("http://radio.local/"), allow_insecure_http=True
        )
        result = await send_webhook(
            target,
            {},
            Settings(),
            resolver=_resolver,
            client_factory=_webhook_factory(seen, redirect),
        )
        assert not result.ok and result.error == "redirect refused"
        assert len(seen) == 1

    asyncio.run(run())


def test_webhook_signature_verifies_and_rejects_tampering() -> None:
    secret, timestamp, body = "secret", "1700000000", b'{"ok":true}'
    sent = signature(secret, timestamp, body)
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(sent, f"sha256={expected}")
    assert not hmac.compare_digest(sent, signature(secret, timestamp, b"tampered"))


def test_webhook_secret_never_logged_or_stored_in_attempts() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []

        def leak(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"secret-value", request=request)

        target = WebhookTarget(
            id="hook",
            name="Hook",
            url=AnyUrl("http://radio.local/"),
            secret="secret-value",
            allow_insecure_http=True,
        )
        result = await send_webhook(
            target,
            {},
            Settings(),
            resolver=_resolver,
            client_factory=_webhook_factory(seen, leak),
        )
        assert result.error is not None
        assert "secret-value" not in result.error

    asyncio.run(run())


def test_webhook_attachment_respects_size_cap_and_root_check(tmp_path: Path) -> None:
    async def run() -> None:
        root = tmp_path / "recordings"
        root.mkdir()
        recording = root / "a.mp3"
        recording.write_bytes(b"0123456789")
        target = WebhookTarget(
            id="hook",
            name="Hook",
            url=AnyUrl("http://radio.local/"),
            include_audio=True,
            allow_insecure_http=True,
        )
        result = await send_webhook(
            target,
            {},
            Settings(recordings_root=root, webhook_attachment_max_bytes=3),
            recording_path=str(recording),
            resolver=_resolver,
            client_factory=_webhook_factory([]),
        )
        assert not result.ok
        outside = tmp_path / "outside.mp3"
        outside.write_bytes(b"x")
        result = await send_webhook(
            target,
            {},
            Settings(recordings_root=root),
            recording_path=str(outside),
            resolver=_resolver,
            client_factory=_webhook_factory([]),
        )
        assert not result.ok

    asyncio.run(run())


def test_webhook_sends_capped_attachment_and_revalidates_enabled_redirects(tmp_path: Path) -> None:
    async def run() -> None:
        root = tmp_path / "recordings"
        root.mkdir()
        recording = root / "a.mp3"
        recording.write_bytes(b"audio")
        requests: list[httpx.Request] = []
        responses = [302, 204]

        def factory(**_kwargs: object) -> httpx.AsyncClient:
            async def handler(request: httpx.Request) -> httpx.Response:
                requests.append(request)
                code = responses.pop(0)
                return httpx.Response(
                    code,
                    headers={"location": "http://radio-two.local/"} if code == 302 else {},
                    request=request,
                )

            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        target = WebhookTarget(
            id="hook",
            name="Hook",
            url=AnyUrl("http://radio.local/"),
            include_audio=True,
            allow_insecure_http=True,
        )
        result = await send_webhook(
            target,
            {},
            Settings(recordings_root=root, webhook_allow_redirects=True),
            recording_path=str(recording),
            resolver=_resolver,
            client_factory=factory,
        )
        assert result.ok and len(requests) == 2
        assert b"audio" in requests[0].content

    asyncio.run(run())


def test_urlsafety_rejects_empty_and_non_socket_responses() -> None:
    async def run() -> None:
        with pytest.raises(UnsafeURL):
            validate_url("ftp://example.com", schemes=frozenset({"http"}))
        with pytest.raises(UnsafeURL):
            await resolve_and_validate(
                "https://radio.local/",
                resolver=lambda *_args, **_kwargs: [(999, 1, 6, "", ("8.8.8.8", 0))],
            )
        with pytest.raises(UnsafeURL):
            await resolve_and_validate(
                "https://radio.local/", resolver=lambda *_args, **_kwargs: []
            )
        with pytest.raises(UnsafeURL):
            await resolve_and_validate(
                "https://radio.local/",
                resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
                allow_private=False,
            )

    asyncio.run(run())


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def add(self, row: Any) -> None:
        self.rows.append(row)

    async def commit(self) -> None:
        return None


def _dispatcher(targets: list[str], rows: list[Any], sleep: Any = asyncio.sleep) -> AlertDispatcher:
    config = AppConfig(
        tone_sets=[tone_set(*targets)],
        alert_targets=[
            WebhookTarget(id=target, name=target, url=AnyUrl("https://example.com"))
            for target in targets
        ],
    )
    return AlertDispatcher(
        config,
        EventBus(),
        lambda: _Session(rows),
        settings=Settings(),
        sleep=sleep,
        jitter=lambda delay: delay,
    )


def test_dispatcher_dedupes_stacked_pages_per_target_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        calls: list[dict[str, object]] = []

        async def sender(*_args: object, **kwargs: object) -> Any:
            calls.append(kwargs)
            return type("Result", (), {"ok": True, "status_code": 200, "error": None})()

        monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", sender)
        dispatcher = _dispatcher(["hook"], [])
        call_id = uuid4()
        event = ToneDetected(call_id, "page", datetime.now(UTC), "radio")
        await dispatcher.handle(event)
        await dispatcher.handle(event)
        assert len(calls) == 1

    asyncio.run(run())


def test_dispatcher_retries_with_backoff_and_records_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        attempts, delays = [0], []
        rows: list[Any] = []

        async def sender(*_args: object, **_kwargs: object) -> Any:
            attempts[0] += 1
            ok = attempts[0] == 3
            return type(
                "Result",
                (),
                {"ok": ok, "status_code": 200 if ok else 500, "error": None if ok else "bad"},
            )()

        async def sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", sender)
        dispatcher = _dispatcher(["hook"], rows, sleep)
        await dispatcher.handle(ToneDetected(uuid4(), "page", datetime.now(UTC), "radio"))
        assert attempts[0] == 3
        assert delays == [1, 2]
        assert [row.attempt_no for row in rows] == [1, 2, 3]
        assert rows[0].error != "secret-value"

    asyncio.run(run())


def test_dispatcher_slow_target_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        fast = asyncio.Event()
        release = asyncio.Event()

        async def sender(target: WebhookTarget, *_args: object, **_kwargs: object) -> Any:
            if target.id == "slow":
                await release.wait()
            else:
                fast.set()
            return type("Result", (), {"ok": True, "status_code": 200, "error": None})()

        monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", sender)
        dispatcher = _dispatcher(["slow", "fast"], [])
        task = asyncio.create_task(
            dispatcher.handle(ToneDetected(uuid4(), "page", datetime.now(UTC), "radio"))
        )
        await asyncio.wait_for(fast.wait(), 1)
        assert not task.done()
        release.set()
        await task

    asyncio.run(run())


def test_dispatcher_test_events_marked_in_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        payloads: list[dict[str, object]] = []

        async def sender(
            _target: WebhookTarget,
            payload: dict[str, object],
            _settings: Settings,
            **_kwargs: object,
        ) -> Any:
            payloads.append(payload)
            return type("Result", (), {"ok": True, "status_code": 200, "error": None})()

        monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", sender)
        dispatcher = _dispatcher(["hook"], [])
        call_id = uuid4()
        await dispatcher.handle(ToneDetected(call_id, "page", datetime.now(UTC), "test", True))
        await dispatcher.handle(CallClosed(call_id, "tested", "test", True))
        assert payloads and all(payload["test"] is True for payload in payloads)

    asyncio.run(run())


def test_dispatcher_recording_phase_and_target_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        payloads: list[dict[str, object]] = []

        async def sender(
            _target: WebhookTarget, payload: dict[str, object], *_args: object, **_kwargs: object
        ) -> Any:
            payloads.append(payload)
            return type("Result", (), {"ok": True, "status_code": 200, "error": None})()

        monkeypatch.setattr("tonewatch.alerts.dispatcher.send_webhook", sender)
        dispatcher = _dispatcher(["hook"], [])
        call_id = uuid4()
        await dispatcher.handle(ToneDetected(call_id, "page", datetime.now(UTC), "radio"))
        payloads.clear()
        await dispatcher.handle(RecordingReady(call_id, "recording.mp3", "mp3"))
        assert payloads[0]["phase"] == "recording_ready"
        await dispatcher._dispatch("missing", "pre_alert", call_id, {})
        await dispatcher._record(call_id, "hook", "closed", 1, True, object())

        mqtt_target = MqttTarget(id="mqtt", name="MQTT")
        mqtt_config = AppConfig(tone_sets=[tone_set("mqtt")], alert_targets=[mqtt_target])
        mqtt_dispatcher = AlertDispatcher(mqtt_config, EventBus(), settings=Settings())

        class Publisher:
            async def publish_call(self, _payload: dict[str, object]) -> None:
                return None

        mqtt_dispatcher._mqtt["mqtt"] = cast("MqttPublisher", Publisher())
        assert (await mqtt_dispatcher._send(mqtt_target, {})).ok

    asyncio.run(run())


def test_script_disabled_unless_allowed_and_enabled(tmp_path: Path) -> None:
    async def run() -> None:
        target = ScriptTarget(
            id="script",
            name="Script",
            executable=str(PYTHON),
            enabled=True,
            args=["-c", "pass"],
        )
        disabled = await run_script(
            target,
            {},
            allow_script_targets=False,
            allowlist_dirs=[PYTHON.parent],
        )
        assert not disabled.ok and "disabled" in (disabled.error or "")

    asyncio.run(run())


def test_script_executable_must_be_in_allowlist_and_not_symlink_escape(tmp_path: Path) -> None:
    target = ScriptTarget(
        id="script", name="Script", executable=str(tmp_path / "missing"), enabled=True
    )
    with pytest.raises(ValueError):
        resolve_executable(target, [tmp_path])
    target = ScriptTarget(id="script", name="Script", executable=str(PYTHON), enabled=True)
    with pytest.raises(ValueError):
        resolve_executable(target, [tmp_path])


def test_script_placeholders_cannot_inject_arguments(tmp_path: Path) -> None:
    async def run() -> None:
        output = tmp_path / "argv.json"
        code = "import json,sys; open(sys.argv[1],'w').write(json.dumps(sys.argv[2:]))"
        target = ScriptTarget(
            id="script",
            name="Script",
            executable=str(PYTHON),
            enabled=True,
            args=["-c", code, str(output), "{toneset}"],
        )
        result = await run_script(
            target,
            {"toneset": "a --evil; rm -rf /"},
            allow_script_targets=True,
            allowlist_dirs=[PYTHON.parent],
        )
        assert result.ok
        assert json.loads(output.read_text(encoding="utf-8")) == ["a --evil; rm -rf /"]

    asyncio.run(run())


def test_script_env_excludes_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        output = tmp_path / "env.txt"
        code = "import os; open(__import__('sys').argv[1],'w').write(' '.join(os.environ))"
        target = ScriptTarget(
            id="script",
            name="Script",
            executable=str(PYTHON),
            enabled=True,
            args=["-c", code, str(output)],
        )
        monkeypatch.setenv("API_TOKEN", "not-for-script")
        result = await run_script(
            target,
            {},
            allow_script_targets=True,
            allowlist_dirs=[PYTHON.parent],
        )
        names = output.read_text(encoding="utf-8")
        assert result.ok and "API_TOKEN" not in names and "SUPERVISOR_TOKEN" not in names

    asyncio.run(run())


def test_script_timeout_kills_and_reaps(tmp_path: Path) -> None:
    async def run() -> None:
        target = ScriptTarget(
            id="script",
            name="Script",
            executable=str(PYTHON),
            enabled=True,
            timeout_s=0.05,
            args=["-c", "import time; time.sleep(2)"],
        )
        result = await run_script(
            target,
            {},
            allow_script_targets=True,
            allowlist_dirs=[PYTHON.parent],
        )
        assert not result.ok and "timeout" in (result.error or "")

    asyncio.run(run())


def test_script_nonzero_output_is_bounded_and_templates_expand() -> None:
    target = ScriptTarget(
        id="script",
        name="Script",
        executable="C:\\allowed.exe",
        enabled=True,
        args=["{call_id}", "{phase}"],
    )
    assert argv_for(target, {"call_id": "x", "phase": "pre_alert"}) == ["x", "pre_alert"]
    with pytest.raises(ValueError):
        ScriptTarget(id="bad", name="Bad", executable="C:\\x", args=["{unknown}"])


def test_script_nonzero_exit_is_reported(tmp_path: Path) -> None:
    async def run() -> None:
        target = ScriptTarget(
            id="script",
            name="Script",
            executable=str(PYTHON),
            enabled=True,
            args=["-c", "import sys; print('failure'); sys.exit(3)"],
        )
        result = await run_script(
            target,
            {},
            allow_script_targets=True,
            allowlist_dirs=[PYTHON.parent],
        )
        assert not result.ok and result.status_code == 3 and "failure" in (result.error or "")

    asyncio.run(run())


def test_mqtt_addon_credentials_from_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"username": "mqtt-user", "password": "mqtt-pass"}}

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    result = asyncio.run(addon_mqtt_credentials(client_factory=lambda **_kwargs: Client()))
    assert result == ("mqtt-user", "mqtt-pass")


def test_mqtt_credentials_are_optional_without_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert asyncio.run(addon_mqtt_credentials()) is None


def test_mqtt_credentials_failure_and_missing_fields_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Broken:
        async def __aenter__(self) -> "Broken":
            raise OSError("unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Empty:
        async def __aenter__(self) -> "Empty":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, *_args: object, **_kwargs: object) -> Any:
            return type(
                "Response",
                (),
                {"raise_for_status": lambda *_args: None, "json": lambda *_args: []},
            )()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    assert asyncio.run(addon_mqtt_credentials(client_factory=lambda **_kwargs: Broken())) is None
    assert asyncio.run(addon_mqtt_credentials(client_factory=lambda **_kwargs: Empty())) is None


def test_mqtt_outbox_and_publish_failure_are_bounded() -> None:
    async def run() -> None:
        class Client:
            async def publish(self, *_args: object, **_kwargs: object) -> None:
                raise OSError("down")

            async def __aexit__(self, *_args: object) -> None:
                raise OSError

        publisher = MqttPublisher(MqttTarget(id="mqtt", name="MQTT"), "instance", outbox_size=1)
        await publisher.publish("a", "one")
        await publisher.publish("b", "two")
        assert next(iter(publisher.outbox)).topic == "b"
        publisher.client = Client()
        publisher._connected.set()
        await publisher.publish("c", "three")
        assert not publisher._connected.is_set() and next(iter(publisher.outbox)).topic == "c"
        await publisher.stop()

    asyncio.run(run())


def test_mqtt_reconnect_service_uses_factory_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr("tonewatch.alerts.mqtt.sys.platform", "linux")

        class Client:
            def __init__(self) -> None:
                self.messages = self
                self.published: list[tuple[str, str]] = []
                self.wait = asyncio.Event()

            async def __aenter__(self) -> "Client":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def publish(self, topic: str, *, payload: str, **_kwargs: object) -> None:
                self.published.append((topic, payload))

            async def __anext__(self) -> Any:
                await self.wait.wait()

        client = Client()
        publisher = MqttPublisher(
            MqttTarget(id="mqtt", name="MQTT"),
            "instance",
            client_factory=lambda **_kwargs: client,
            sleep=lambda _delay: asyncio.sleep(0),
        )
        await publisher.start()
        await asyncio.wait_for(publisher._connected.wait(), 1)
        await publisher.publish_call({"call_id": "x"})
        assert any(topic.endswith("/call") for topic, _payload in client.published)
        await publisher.stop()

    asyncio.run(run())


def test_mqtt_windows_runs_client_in_selector_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr("tonewatch.alerts.mqtt.sys.platform", "win32")
        main_thread = threading.get_ident()
        entered = threading.Event()
        published: list[tuple[str, str, int]] = []

        class Client:
            def __init__(self) -> None:
                self.messages = self
                self.wait = asyncio.Event()

            async def __aenter__(self) -> "Client":
                assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
                assert threading.get_ident() != main_thread
                entered.set()
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def publish(self, topic: str, *, payload: str, **_kwargs: object) -> None:
                published.append((topic, payload, threading.get_ident()))

            async def __anext__(self) -> Any:
                await self.wait.wait()
                return None

        publisher = MqttPublisher(
            MqttTarget(id="mqtt", name="MQTT"),
            "instance",
            client_factory=lambda **_kwargs: Client(),
            sleep=lambda _delay: asyncio.sleep(0),
        )
        await publisher.start()
        assert await asyncio.to_thread(entered.wait, 2.0)
        await publisher.publish_call({"call_id": "windows"})
        assert any(
            topic.endswith("/call") and payload.find("windows") >= 0
            for topic, payload, _ in published
        )
        assert all(thread_id != main_thread for _topic, _payload, thread_id in published)
        thread = publisher._thread
        await publisher.stop()
        assert thread is not None and not thread.is_alive()

    asyncio.run(run())


def test_mqtt_publishes_call_and_health_with_lwt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        monkeypatch.setattr("tonewatch.alerts.mqtt.sys.platform", "linux")

        class Broker:
            def __init__(self) -> None:
                self.queues: list[asyncio.Queue[tuple[str, str]]] = []

            def client(self, **kwargs: object) -> "Client":
                queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
                self.queues.append(queue)
                return Client(self, queue, kwargs.get("will"))

            async def publish(self, topic: str, payload: str) -> None:
                for queue in self.queues:
                    await queue.put((topic, payload))

        class Client:
            def __init__(
                self, broker: Broker, queue: asyncio.Queue[tuple[str, str]], will: object = None
            ) -> None:
                self.broker, self.queue, self.will = broker, queue, will
                self.messages = self

            async def __aenter__(self) -> "Client":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def subscribe(self, _topic: str) -> None:
                return None

            def __aiter__(self) -> "Client":
                return self

            async def __anext__(self) -> Any:
                return await self.queue.get()

            async def publish(self, topic: str, *, payload: str, **_kwargs: object) -> None:
                await self.broker.publish(topic, payload)

        broker = Broker()
        subscriber = broker.client()
        await subscriber.__aenter__()
        await subscriber.subscribe("tonewatch/instance/#")
        publisher = MqttPublisher(
            MqttTarget(id="mqtt", name="MQTT"),
            "instance",
        )
        publisher.client = broker.client()
        await publisher.client.__aenter__()
        publisher._connected.set()
        await publisher.client.publish(
            publisher.availability_topic, payload="online", qos=1, retain=True
        )
        await publisher.publish_call({"call_id": "call", "phase": "pre_alert", "test": True})
        await publisher.publish_health("radio", True)
        messages: list[tuple[str, str]] = []
        while len(messages) < 3:
            message = await asyncio.wait_for(subscriber.__anext__(), 3)
            messages.append(message)
        assert any(
            topic.endswith("/availability") and payload == "online" for topic, payload in messages
        )
        assert any(
            topic.endswith("/call") and json.loads(payload)["call_id"] == "call"
            for topic, payload in messages
        )
        assert any(
            topic.endswith("/health/radio") and payload == "online" for topic, payload in messages
        )
        await publisher.stop()
        offline = await asyncio.wait_for(subscriber.__anext__(), 3)
        assert offline[0].endswith("/availability") and offline[1] == "offline"
        await subscriber.__aexit__(None, None, None)

    asyncio.run(run())


def test_ha_discovery_payloads_and_retained_clear_on_delete() -> None:
    async def run() -> None:
        class Publisher:
            availability_topic = "tonewatch/instance/availability"

            def __init__(self) -> None:
                self.messages: list[tuple[str, object, bool]] = []

            async def publish(self, topic: str, payload: object, *, retain: bool = False) -> None:
                self.messages.append((topic, payload, retain))

        publisher = Publisher()
        discovery = HADiscovery(publisher, "instance")
        first = AppConfig(
            tone_sets=[tone_set()],
            sources=[FileSource(id="radio", name="Radio", path="radio.wav")],
            alert_targets=[],
        )
        await discovery.publish(first)
        assert all(retain for _topic, _payload, retain in publisher.messages)
        old_topics = {topic for topic, _payload, _retain in publisher.messages}
        publisher.messages.clear()
        await discovery.publish(AppConfig())
        cleared = {topic for topic, payload, _retain in publisher.messages if payload == ""}
        assert (
            old_topics
            - {
                discovery._topic("sensor", "last_call"),
                discovery._topic("binary_sensor", "call_active"),
            }
            <= cleared
        )

    asyncio.run(run())
