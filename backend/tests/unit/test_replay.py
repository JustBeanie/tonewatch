import time
from pathlib import Path

import numpy as np
import pytest

from tonewatch.api.routes import replay as replay_routes
from tonewatch.api.routes.replay import classify_replay, summarize_replay
from tonewatch.config.models import AppConfig


def test_replay_classification_and_summary() -> None:
    items = [
        classify_replay("call-1", ["fire"], ["fire"]),
        classify_replay("call-unchanged", [], [], unchanged_label="unchanged"),
        classify_replay("call-2", ["fire"], []),
        classify_replay("upload-1", [], ["ems"]),
    ]

    assert [item["classification"] for item in items] == [
        "would_detect",
        "unchanged",
        "would_miss",
        "new_detection",
    ]
    assert summarize_replay(items) == {
        "would_detect": 1,
        "would_miss": 1,
        "new_detection": 1,
        "unchanged": 1,
        "skipped": 0,
    }


def test_replay_decoder_handles_wav_and_resampled_encoded_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "fixture.wav"
    wav.write_bytes(b"not used")
    expected = np.ones(160, dtype=np.float32)
    monkeypatch.setattr(replay_routes, "_read_wav", lambda _path: (expected, 16_000))
    samples, duration = replay_routes._decode_audio(wav)
    assert samples is expected and duration == 0.01

    class Stream:
        type = "audio"
        rate = 8_000

    class Frame:
        def to_ndarray(self) -> np.ndarray:
            return np.array([[0, 32767]], dtype=np.int16)

    class IntegerFrame:
        def to_ndarray(self) -> np.ndarray:
            return np.array([0, 32767], dtype=np.int16)

    class Container:
        def __init__(self) -> None:
            self.streams = [Stream()]

        def __enter__(self) -> "Container":
            return self

        def __exit__(self, *_args: object) -> None:
            return

        def decode(self, _stream: object) -> list[object]:
            return [Frame(), IntegerFrame()]

    monkeypatch.setattr(replay_routes.av, "open", lambda *_args, **_kwargs: Container())
    encoded, encoded_duration = replay_routes._decode_audio(tmp_path / "fixture.mp3")
    assert encoded.size == 8 and encoded_duration == encoded.size / 16_000
    Stream.rate = 16_000
    native, native_duration = replay_routes._decode_audio(tmp_path / "fixture.mp3")
    assert native.size == 4 and native_duration == native.size / 16_000


def test_replay_decoder_rejects_missing_audio_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Container:
        def __init__(self) -> None:
            self.streams: list[object] = []

        def __enter__(self) -> "Container":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(replay_routes.av, "open", lambda *_args, **_kwargs: Container())
    with pytest.raises(ValueError, match="no decodable audio"):
        replay_routes._decode_audio(tmp_path / "fixture.mp3")


def test_replay_draft_validation_and_upload_cleanup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(replay_routes.HTTPException, match="draft must be an object"):
        replay_routes._draft_config(AppConfig(), None)
    with pytest.raises(replay_routes.HTTPException, match="tuning must be an object"):
        replay_routes._draft_config(AppConfig(), {"tuning": []})
    upload = tmp_path / "expired.wav"
    upload.write_bytes(b"x")

    def fail_stat(_path: Path) -> object:
        raise OSError

    monkeypatch.setattr(Path, "stat", fail_stat)
    replay_routes._clean_uploads(tmp_path, now=10_000)


@pytest.mark.asyncio
async def test_replay_detection_enforces_per_item_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def never_finishes(*_args: object, **_kwargs: object) -> tuple[np.ndarray, float]:
        time.sleep(0.05)
        return np.zeros(1), 0.0

    monkeypatch.setattr(replay_routes, "REPLAY_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(replay_routes, "_decode_audio", never_finishes)
    with pytest.raises(TimeoutError):
        await replay_routes._run_detection(Path("ignored.mp3"), AppConfig(), {})
