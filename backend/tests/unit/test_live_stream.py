"""Unit coverage for live token boundaries and bounded listener fan-out."""

import asyncio
import os
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from tonewatch.streaming.live import (
    LiveHub,
    make_live_token,
    read_or_create_live_secret,
    verify_live_token,
)


def test_live_token_is_scoped_and_rotation_invalidates_it(tmp_path: Path) -> None:
    token = make_live_token(tmp_path, "radio", 2_000_000_000)
    assert verify_live_token(tmp_path, "radio", token, now=1_900_000_000)
    assert not verify_live_token(tmp_path, "other", token, now=1_900_000_000)
    (tmp_path / "live_stream_secret").write_bytes(b"rotated secret")
    assert not verify_live_token(tmp_path, "radio", token, now=1_900_000_000)


def test_hub_has_no_encoder_without_listeners(monkeypatch) -> None:
    created = 0

    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            nonlocal created
            created += 1

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"chunk"]

        def close(self) -> None:
            pass

    monkeypatch.setattr("tonewatch.streaming.live._Mp3Encoder", Encoder)
    hub = LiveHub()
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    assert created == 0
    listener = hub.add_listener("radio")
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    assert created == 1
    assert listener.queue.get_nowait() == b"chunk"
    hub.remove_listener(listener)
    assert hub.listener_count == 0


def test_feed_drops_oldest_without_awaiting_listener(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"chunk"]

        def close(self) -> None:
            pass

    monkeypatch.setattr("tonewatch.streaming.live._Mp3Encoder", Encoder)
    hub = LiveHub(queue_seconds=0.2)
    listener = hub.add_listener("radio")
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    assert listener.queue.qsize() == 2
    assert not listener.closed


def test_stalled_listener_does_not_delay_feed(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"chunk"]

        def close(self) -> None:
            pass

    monkeypatch.setattr("tonewatch.streaming.live._Mp3Encoder", Encoder)
    hub = LiveHub(queue_seconds=0.2)
    hub.add_listener("radio")
    started = perf_counter()
    for _ in range(100):
        hub.feed("radio", np.zeros(1600, dtype=np.float32))
    assert perf_counter() - started < 0.1


def test_listener_that_catches_up_is_not_removed_after_lag_window(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"chunk"]

        def close(self) -> None:
            pass

    now = 0.0
    monkeypatch.setattr("tonewatch.streaming.live.time.monotonic", lambda: now)
    monkeypatch.setattr("tonewatch.streaming.live._Mp3Encoder", Encoder)
    hub = LiveHub(queue_seconds=0.2, max_lag_s=2.0)
    listener = hub.add_listener("radio")
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    listener.queue.get_nowait()
    listener.queue.get_nowait()
    now = 10.0
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    assert not listener.closed


@pytest.mark.asyncio
async def test_removed_listener_get_finishes_and_releases_encoder(monkeypatch) -> None:
    class Encoder:
        def __init__(self, _bitrate: int) -> None:
            pass

        def encode(self, _samples: np.ndarray) -> list[bytes]:
            return [b"chunk"]

        def close(self) -> None:
            pass

    monkeypatch.setattr("tonewatch.streaming.live._Mp3Encoder", Encoder)
    hub = LiveHub(queue_seconds=0.2, max_lag_s=0.0)
    listener = hub.add_listener("radio")
    consumer = asyncio.create_task(listener.get())
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    hub.feed("radio", np.zeros(1600, dtype=np.float32))
    listener.queue.get_nowait()
    hub.remove_listener(listener)
    assert await asyncio.wait_for(consumer, timeout=1.0) == b""
    assert hub.listener_count == 0


def test_live_secret_creation_race_returns_one_secret(monkeypatch, tmp_path: Path) -> None:
    real_open = os.open
    calls = 0

    def racing_open(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            fd = real_open(args[0], os.O_WRONLY | os.O_CREAT, 0o600)
            os.write(fd, b"winner")
            os.close(fd)
            raise FileExistsError(args[0])
        return real_open(args[0], *args[1:], **kwargs)

    monkeypatch.setattr("tonewatch.streaming.live.os.open", racing_open)
    first = read_or_create_live_secret(tmp_path)
    second = read_or_create_live_secret(tmp_path)
    assert first == second
