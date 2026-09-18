"""Bounded per-source MP3 restreaming and short-lived URL tokens."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import os
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import av
import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

SECRET_FILE_MODE = 0o600
MAX_NONCE_LENGTH = 64
MAX_SIGNATURE_LENGTH = 128


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def live_secret_path(data_dir: Path) -> Path:
    """Return the dedicated live-stream signing secret path."""
    return data_dir / "live_stream_secret"


def read_or_create_live_secret(data_dir: Path) -> bytes:
    """Read or create the owner-readable live-stream signing secret."""
    path = live_secret_path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.stat().st_mode & 0o777 != SECRET_FILE_MODE:
            path.chmod(SECRET_FILE_MODE)
        return path.read_bytes()
    secret = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_FILE_MODE)
    except FileExistsError:
        return path.read_bytes()
    try:
        os.write(fd, secret)
    finally:
        os.close(fd)
    if os.name != "nt":
        path.chmod(SECRET_FILE_MODE)
    return path.read_bytes()


def make_live_token(data_dir: Path, source_id: str, expires_at: int) -> str:
    """Create a versioned, source-scoped live-stream token."""
    nonce = _b64(secrets.token_bytes(16))
    body = f"live|{source_id}|{expires_at}|{nonce}".encode()
    signature = _b64(hmac.new(read_or_create_live_secret(data_dir), body, hashlib.sha256).digest())
    return f"v1.{expires_at}.{nonce}.{signature}"


def verify_live_token(data_dir: Path, source_id: str, token: str, now: int | None = None) -> bool:
    """Verify a live token's format, expiry, source scope, and HMAC."""
    try:
        version, expiry_text, nonce, signature = token.split(".")
        expiry = int(expiry_text)
        if version != "v1" or expiry <= int(time.time() if now is None else now):
            return False
        if (
            not nonce
            or not signature
            or len(nonce) > MAX_NONCE_LENGTH
            or len(signature) > MAX_SIGNATURE_LENGTH
        ):
            return False
        body = f"live|{source_id}|{expiry}|{nonce}".encode()
        expected = _b64(
            hmac.new(read_or_create_live_secret(data_dir), body, hashlib.sha256).digest()
        )
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


class LiveListener:
    """A listener queue; its consumer is responsible for awaiting ``get``."""

    def __init__(self, source_id: str, max_chunks: int) -> None:
        """Create a bounded queue for one HTTP consumer."""
        self.source_id = source_id
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_chunks)
        self.closed = False
        self._full_since: float | None = None

    async def get(self) -> bytes:
        """Wait for the next encoded MP3 chunk."""
        return await self.queue.get()

    def close(self) -> None:
        """Mark this consumer as disconnected."""
        if self.closed:
            return
        self.closed = True
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(b"")


@dataclass(slots=True)
class _SourceStream:
    listeners: set[LiveListener]
    encoder: Any


class _Mp3Encoder:
    def __init__(self, bitrate_kbps: int) -> None:
        self._sink = io.BytesIO()
        self.container = av.open(self._sink, mode="w", format="mp3")
        self.stream = self.container.add_stream("mp3", rate=44_100)
        self.stream.layout = "mono"
        self.stream.bit_rate = bitrate_kbps * 1000
        self.resampler = av.audio.resampler.AudioResampler(
            format="fltp", layout="mono", rate=44_100
        )

    def encode(self, samples: np.ndarray) -> list[bytes]:
        pcm = np.asarray(samples, dtype=np.float32)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = 16_000
        packets: list[bytes] = []
        for resampled in self.resampler.resample(frame):
            packets.extend(bytes(packet) for packet in self.stream.encode(resampled))
        return packets

    def close(self) -> None:
        for resampled in self.resampler.resample(None):
            for _packet in self.stream.encode(resampled):
                pass
        for _packet in self.stream.encode():
            pass
        self.container.close()


class LiveHub:
    """Non-blocking, bounded live MP3 fan-out for normalized source frames."""

    def __init__(
        self,
        *,
        bitrate_kbps: int = 48,
        queue_seconds: float = 2.0,
        max_lag_s: float = 10.0,
        listener_changed: Any = None,
    ) -> None:
        """Create a live hub with bounded queues and listener lag policy."""
        self.bitrate_kbps = bitrate_kbps
        self.max_chunks = max(1, round(queue_seconds * 10))
        self.max_lag_s = max_lag_s
        self.listener_changed = listener_changed
        self._streams: dict[str, _SourceStream] = {}

    @property
    def listener_count(self) -> int:
        """Return the total number of connected live listeners."""
        return sum(len(stream.listeners) for stream in self._streams.values())

    def listeners_for(self, source_id: str) -> int:
        """Return the number of connected listeners for one source."""
        return len(self._streams.get(source_id, _SourceStream(set(), None)).listeners)

    def add_listener(self, source_id: str) -> LiveListener:
        """Start a source encoder if needed and add one listener."""
        stream = self._streams.get(source_id)
        if stream is None:
            stream = _SourceStream(set(), _Mp3Encoder(self.bitrate_kbps))
            self._streams[source_id] = stream
        listener = LiveListener(source_id, self.max_chunks)
        stream.listeners.add(listener)
        self._changed(source_id)
        return listener

    def configure(
        self,
        *,
        bitrate_kbps: int,
        queue_seconds: float,
        max_lag_s: float,
    ) -> None:
        """Apply live-stream settings to future frames and listeners."""
        self.bitrate_kbps = bitrate_kbps
        self.max_chunks = max(1, round(queue_seconds * 10))
        self.max_lag_s = max_lag_s

    def remove_listener(self, listener: LiveListener) -> None:
        """Remove a listener and release its source encoder when unused."""
        stream = self._streams.get(listener.source_id)
        if stream is None:
            return
        listener.close()
        stream.listeners.discard(listener)
        if not stream.listeners:
            stream.encoder.close()
            del self._streams[listener.source_id]
        self._changed(listener.source_id)

    def close_all(self) -> None:
        """Disconnect every active listener, preserving clean stream teardown."""
        for stream in tuple(self._streams.values()):
            for listener in tuple(stream.listeners):
                self.remove_listener(listener)

    def feed(self, source_id: str, samples: np.ndarray, *, gate_open: bool = True) -> None:
        """Encode and fan out one frame without awaiting any listener."""
        stream = self._streams.get(source_id)
        if stream is None:
            return
        pcm = samples if gate_open else np.zeros_like(samples)
        for chunk in stream.encoder.encode(pcm):
            for listener in tuple(stream.listeners):
                if listener.closed:
                    continue
                if not listener.queue.full():
                    listener._full_since = None
                if listener.queue.full():
                    listener.queue.get_nowait()
                    if listener._full_since is None:
                        listener._full_since = time.monotonic()
                listener.queue.put_nowait(chunk)
                if (
                    listener._full_since is not None
                    and time.monotonic() - listener._full_since > self.max_lag_s
                ):
                    self.remove_listener(listener)

    def _changed(self, source_id: str) -> None:
        if self.listener_changed is not None:
            self.listener_changed(source_id, self.listeners_for(source_id), self.listener_count)
