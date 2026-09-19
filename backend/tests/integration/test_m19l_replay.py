"""Adversarial M19.12 replay API tests."""

from __future__ import annotations

import asyncio
import hashlib
import io
import wave
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import numpy as np
import pytest
from pydantic import AnyUrl

from tonewatch.api.app import create_app
from tonewatch.api.routes import replay as replay_routes
from tonewatch.config.history import ConfigHistory
from tonewatch.config.models import (
    AppConfig,
    RecordingPolicy,
    ToneSet,
    ToneSpec,
    WebhookTarget,
)
from tonewatch.config.store import ConfigStore
from tonewatch.dsp.generator import concat, silence, tone, voice_like
from tonewatch.recording.encoder import AudioEncoder
from tonewatch.settings import Settings
from tonewatch.storage.models import Call, CallToneSet, Recording

if TYPE_CHECKING:
    from pathlib import Path


def _toneset(identifier: str, frequency: float, *, min_s: float = 0.1) -> ToneSet:
    return ToneSet(
        id=identifier,
        name=identifier.title(),
        sequence=[ToneSpec(freq_hz=frequency, min_s=min_s)],
        record=RecordingPolicy(post_s=1, silence_stop_s=0.5),
    )


def _wav_bytes(samples: np.ndarray) -> bytes:
    handle = io.BytesIO()
    with wave.open(handle, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return handle.getvalue()


async def _client_for(
    root: Path, config: AppConfig, *, clock: Any = None
) -> tuple[Any, httpx.AsyncClient, str]:
    ConfigStore(root).save(config)
    app = create_app(Settings(data_dir=root, zeroconf_enabled=False), clock=clock)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    app.state.test_lifespan = lifespan
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    token = (root / "api_token").read_text(encoding="ascii").strip()
    return app, client, token


async def _close_client(app: Any, client: httpx.AsyncClient) -> None:
    await client.aclose()
    await app.state.test_lifespan.__aexit__(None, None, None)


async def _upload(client: httpx.AsyncClient, token: str, samples: np.ndarray) -> str:
    response = await client.post(
        "/api/admin/replay/uploads",
        files={"file": ("fixture.wav", _wav_bytes(samples), "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_replay_classification_from_generated_wavs_and_empty_draft(tmp_path: Path) -> None:
    config = AppConfig(tone_sets=[_toneset("page", 1000)])
    app, client, token = await _client_for(tmp_path, config)
    try:
        matching = await _upload(client, token, concat(silence(0.2), tone(1000, 0.7)))
        moved = await _upload(client, token, concat(silence(0.2), tone(1000, 0.7)))
        new_tone = await _upload(client, token, concat(silence(0.2), tone(1200, 0.7)))
        headers = {"Authorization": f"Bearer {token}"}

        async def replay(upload_id: str, draft: list[dict[str, Any]]) -> dict[str, Any]:
            response = await client.post(
                "/api/admin/replay",
                json={"draft": {"tone_sets": draft}, "calls": None, "uploads": [upload_id]},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            return response.json()

        matching_result = await replay(matching, [_toneset("page", 1000).model_dump(mode="json")])
        moved_result = await replay(moved, [_toneset("page", 1100).model_dump(mode="json")])
        new_result = await replay(new_tone, [_toneset("new-page", 1200).model_dump(mode="json")])
        empty_result = await replay(matching, [])

        assert matching_result["items"][0]["classification"] == "would_detect"
        assert moved_result["items"][0]["classification"] == "would_miss"
        assert new_result["items"][0]["classification"] == "new_detection"
        assert empty_result["items"][0]["draft"] == []
        assert matching_result["summary"] == {
            "would_detect": 1,
            "would_miss": 0,
            "new_detection": 0,
            "unchanged": 0,
            "skipped": 0,
        }
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_seeded_encoded_call_documents_tone_trimmed_limitation(
    tmp_path: Path,
) -> None:
    config = AppConfig(tone_sets=[_toneset("page", 1000)])
    app, client, token = await _client_for(tmp_path, config)
    try:
        call_id = uuid4()
        started = datetime(2026, 1, 1, tzinfo=UTC)
        raw = concat(silence(0.1), tone(1000, 0.7), voice_like(1.0))
        encoder = AudioEncoder(app.state.settings.recording_path)
        encoded_path = app.state.settings.recording_path / "2026" / "01" / "01" / f"{call_id}.mp3"
        encoded_path.parent.mkdir(parents=True, exist_ok=True)
        encoder.encode_samples_to_path(
            encoded_path,
            concat(silence(0.1), raw[round(0.8 * 16_000) :], silence(0.5)),
            fmt="mp3",
            title="trimmed page",
            toneset_ids={"page"},
            source_id="radio",
            call_id=str(call_id),
        )
        async with app.state.session_factory() as session:
            session.add(Call(id=call_id, started_at=started, source_id="radio", status="recorded"))
            session.add(
                CallToneSet(
                    call_id=call_id,
                    toneset_id="page",
                    detected_at=started,
                    matched_segment_freqs=[1000],
                )
            )
            session.add(
                Recording(
                    call_id=call_id,
                    format="mp3",
                    path=str(encoded_path),
                    duration_s=0.7,
                    size_bytes=encoded_path.stat().st_size,
                )
            )
            await session.commit()
        response = await client.post(
            "/api/admin/replay",
            json={
                "draft": {"tone_sets": [_toneset("page", 1000).model_dump(mode="json")]},
                "calls": {"last_n": 1},
                "uploads": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["items"][0]["actual"] == []
        assert payload["items"][0]["recorded"] == ["page"]
        assert payload["items"][0]["classification"] == "unchanged"
        assert payload["summary"]["would_miss"] == 0
        assert payload["summary"]["new_detection"] == 0

        loose = await client.post(
            "/api/admin/replay",
            json={
                "draft": {
                    "tone_sets": [
                        ToneSet(
                            id="voice",
                            name="Voice",
                            sequence=[ToneSpec(freq_hz=250, tol_pct=10, min_s=0.001)],
                            record=RecordingPolicy(post_s=1, silence_stop_s=0.5),
                        ).model_dump(mode="json")
                    ],
                    "tuning": {
                        "band": (150, 3000),
                        "purity_min": 0.0,
                        "level_min_dbfs": -100,
                        "window": 256,
                        "hop": 80,
                        "segment_tol_pct": 1,
                        "max_dropout_frames": 2,
                    },
                },
                "calls": {"last_n": 1},
                "uploads": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert loose.status_code == 200, loose.text
        assert loose.json()["items"][0]["recorded"] == ["page"]
        assert loose.json()["items"][0]["classification"] == "new_detection", loose.json()
        assert payload["limitations"] == [
            "Stored call recordings are tone-trimmed voice clips. "
            "Replaying them checks that the draft doesn't start triggering on voice traffic. "
            "Use uploaded WAVs to test tone detection."
        ]
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_validation_secret_restore_and_non_persistence(tmp_path: Path) -> None:
    secret = "stored-secret"  # noqa: S105 -- fixture-only credential.
    config = AppConfig(
        tone_sets=[_toneset("page", 1000)],
        alert_targets=[
            WebhookTarget(
                id="hook",
                name="Hook",
                url=AnyUrl("https://example.test/hook"),
                secret=secret,
            )
        ],
    )
    app, client, token = await _client_for(tmp_path, config)
    try:
        upload_id = await _upload(client, token, concat(silence(0.2), tone(1000, 0.7)))
        headers = {"Authorization": f"Bearer {token}"}
        before_hash = hashlib.sha256((tmp_path / "config.yaml").read_bytes()).hexdigest()
        before_versions = len(ConfigHistory(tmp_path).list_versions())
        before_config = app.state.config
        draft = app.state.config.model_dump(mode="json")
        masked = "[REDACTED]"
        draft["alert_targets"][0]["secret"] = masked
        response = await client.post(
            "/api/admin/replay",
            json={"draft": draft, "calls": None, "uploads": [upload_id]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert hashlib.sha256((tmp_path / "config.yaml").read_bytes()).hexdigest() == before_hash
        assert len(ConfigHistory(tmp_path).list_versions()) == before_versions
        assert app.state.config == before_config

        invalid = dict(draft)
        invalid["tone_sets"] = [
            {
                "id": "bad",
                "name": "Bad",
                "sequence": [{"freq_hz": 100, "min_s": 1}],
            }
        ]
        assert (
            await client.post(
                "/api/admin/replay",
                json={"draft": invalid, "calls": None, "uploads": [upload_id]},
                headers=headers,
            )
        ).status_code == 422
        missing_secret = dict(draft)
        missing_secret["alert_targets"] = [
            {
                "id": "other",
                "name": "Other",
                "type": "webhook",
                "url": "https://example.test",
                "secret": masked,
            }
        ]
        assert (
            await client.post(
                "/api/admin/replay",
                json={"draft": missing_secret, "calls": None, "uploads": [upload_id]},
                headers=headers,
            )
        ).status_code == 422
        audit = await client.get("/api/audit?event_type=replay", headers=headers)
        assert audit.status_code == 200
        assert audit.json()["items"]
        assert secret not in audit.text
        assert "[REDACTED]" not in audit.json()["items"][0]["details"]
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_auth_path_confinement_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, token = await _client_for(tmp_path, AppConfig())
    try:
        no_auth = await client.post(
            "/api/admin/replay", json={"draft": {}, "calls": None, "uploads": []}
        )
        assert no_auth.status_code == 401
        outside_call = Call(
            id=uuid4(), started_at=datetime.now(UTC), source_id="radio", status="recorded"
        )
        outside = tmp_path / "outside.mp3"
        outside.write_bytes(b"must not be opened")
        async with app.state.session_factory() as session:
            session.add(outside_call)
            session.add(
                Recording(
                    call_id=outside_call.id,
                    format="mp3",
                    path=str(outside),
                    duration_s=1,
                    size_bytes=outside.stat().st_size,
                )
            )
            await session.commit()
        opened: list[Path] = []
        original = replay_routes._decode_audio

        def track(path: Path) -> tuple[np.ndarray, float]:
            opened.append(path)
            return original(path)

        monkeypatch.setattr(replay_routes, "_decode_audio", track)
        response = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": {"last_n": 1}, "uploads": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["classification"] == "skipped"
        assert "outside root" in response.json()["items"][0]["reason"]
        assert outside not in opened
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_upload_limits_random_ids_expiry_and_path_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [10_000.0]
    app, client, token = await _client_for(tmp_path, AppConfig(), clock=lambda: now[0])
    try:
        headers = {"Authorization": f"Bearer {token}"}
        oversized = await client.post(
            "/api/admin/replay/uploads",
            files={"file": ("oversize.wav", b"x" * (20 * 1024 * 1024 + 1), "audio/wav")},
            headers=headers,
        )
        assert oversized.status_code == 413
        non_wav = await client.post(
            "/api/admin/replay/uploads",
            files={"file": ("bad.wav", b"not wav", "audio/wav")},
            headers=headers,
        )
        assert non_wav.status_code == 422
        upload_id = await _upload(client, token, tone(1000, 0.2))
        assert upload_id not in {"..", "../replay-uploads"}
        stored = list((tmp_path / "replay-uploads").glob("*.wav"))
        assert len(stored) == 1 and stored[0].stem == upload_id and stored[0].name != "fixture.wav"
        traversal = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": [".."]},
            headers=headers,
        )
        assert traversal.status_code == 404
        unknown = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": ["missing"]},
            headers=headers,
        )
        assert unknown.status_code == 404
        now[0] += 3601
        expired = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": [upload_id]},
            headers=headers,
        )
        assert expired.status_code == 404

        class TooLongWave:
            def __enter__(self) -> TooLongWave:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def getnframes(self) -> int:
                return 601

            def getframerate(self) -> int:
                return 1

        monkeypatch.setattr(replay_routes.wave, "open", lambda *_args, **_kwargs: TooLongWave())
        too_long = await client.post(
            "/api/admin/replay/uploads",
            files={"file": ("long.wav", b"fixture", "audio/wav")},
            headers=headers,
        )
        assert too_long.status_code == 413
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_concurrency_and_total_audio_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, token = await _client_for(tmp_path, AppConfig())
    try:
        first = await _upload(client, token, silence(0.2))
        second = await _upload(client, token, silence(0.2))

        async def slow_detection(
            _path: Path, _config: AppConfig, _tuning: dict[str, Any]
        ) -> tuple[list[dict[str, Any]], float]:
            await asyncio.sleep(0.1)
            return [], 0.0

        monkeypatch.setattr(replay_routes, "_run_detection", slow_detection)
        headers = {"Authorization": f"Bearer {token}"}
        request: dict[str, object] = {
            "draft": {},
            "calls": None,
            "uploads": [first],
        }
        first_task, second_task = await asyncio.gather(
            client.post("/api/admin/replay", json=request, headers=headers),
            client.post("/api/admin/replay", json=request, headers=headers),
        )
        assert sorted([first_task.status_code, second_task.status_code]) == [200, 429]

        def long_decode(_path: Path) -> tuple[np.ndarray, float]:
            return np.zeros(1, dtype=np.float32), 400.0

        async def empty_detection(
            _path: Path, _config: AppConfig, _tuning: dict[str, Any]
        ) -> tuple[list[dict[str, Any]], float]:
            return [], 400.0

        monkeypatch.setattr(replay_routes, "_decode_audio", long_decode)
        monkeypatch.setattr(replay_routes, "_run_detection", empty_detection)
        capped = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": [first, second]},
            headers=headers,
        )
        assert capped.status_code == 200
        assert capped.json()["summary"]["skipped"] == 1
        assert "total audio cap" in capped.json()["items"][1]["reason"]
    finally:
        await _close_client(app, client)


@pytest.mark.asyncio
async def test_replay_reports_decode_failure_and_item_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DecodeFailureError(ValueError):
        def __init__(self) -> None:
            super().__init__("decode failed")

    class ItemTimeoutError(TimeoutError):
        def __init__(self) -> None:
            super().__init__("item timed out")

    app, client, token = await _client_for(tmp_path, AppConfig())
    try:
        upload_id = await _upload(client, token, silence(0.2))
        headers = {"Authorization": f"Bearer {token}"}

        def decode_failure(_path: Path) -> tuple[np.ndarray, float]:
            raise DecodeFailureError

        monkeypatch.setattr(replay_routes, "_decode_audio", decode_failure)
        failed = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": [upload_id]},
            headers=headers,
        )
        assert failed.status_code == 200
        assert failed.json()["items"][0]["reason"] == "decode failed"

        monkeypatch.setattr(replay_routes, "_decode_audio", lambda _path: (np.zeros(1), 0.1))

        async def timeout_detection(
            _path: Path, _config: AppConfig, _tuning: dict[str, Any]
        ) -> tuple[list[dict[str, Any]], float]:
            raise ItemTimeoutError

        monkeypatch.setattr(replay_routes, "_run_detection", timeout_detection)
        timed_out = await client.post(
            "/api/admin/replay",
            json={"draft": {}, "calls": None, "uploads": [upload_id]},
            headers=headers,
        )
        assert timed_out.status_code == 200
        assert timed_out.json()["items"][0]["reason"] == "item timed out"
    finally:
        await _close_client(app, client)
