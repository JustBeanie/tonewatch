"""Authentication and CSRF protections for the HTTP API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import HTTPException, Request, status

from tonewatch.logging import SecretHolder

if TYPE_CHECKING:
    from tonewatch.settings import Settings


def token_path(settings: Settings) -> Path:
    return settings.data_dir / "api_token"


def read_or_create_token(settings: Settings) -> str:
    path = token_path(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        _protect_secret_file(path)
        return path.read_text(encoding="ascii").strip()
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="ascii")
    _protect_secret_file(path)
    return token


def rotate_token(settings: Settings) -> str:
    path = token_path(settings)
    token = secrets.token_urlsafe(32)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_secret(path, token + "\n")
    return token


def atomic_write_secret(path: Path, content: str | bytes) -> None:
    """Replace a secret file atomically and keep it owner-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        handle: Any = (
            os.fdopen(fd, "wb")
            if isinstance(content, bytes)
            else os.fdopen(fd, "w", encoding="utf-8")
        )
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _protect_secret_file(path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def _protect_secret_file(path: Path) -> None:
    """Keep locally stored secrets owner-readable on POSIX filesystems."""
    if os.name == "nt":
        return
    try:
        if path.stat().st_mode & 0o777 != 0o600:
            path.chmod(0o600)
            structlog.get_logger("tonewatch.auth").warning(
                "secret file permissions corrected", path=str(path), permissions="0600"
            )
    except OSError:
        with suppress(OSError):
            path.chmod(0o600)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _scheme, salt_hex, digest_hex = encoded.split("$", 2)
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=2**15,
            r=8,
            p=1,
            dklen=32,
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


@dataclass
class Session:
    csrf: str
    last_used: float


class AuthState:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.time) -> None:
        self.settings = settings
        self.clock = clock
        self.token = read_or_create_token(settings)
        self.secret_holder = SecretHolder(self.token)
        self.previous_token: str | None = None
        self.previous_valid_until: float | None = None
        grace_path = settings.data_dir / "api_token_grace"
        if grace_path.is_file():
            try:
                grace = json.loads(grace_path.read_text(encoding="utf-8"))
                if self.clock() < float(grace["valid_until"]):
                    self.previous_token = str(grace["token"])
                    self.previous_valid_until = float(grace["valid_until"])
                    self.secret_holder.previous = self.previous_token
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        self.sessions: dict[str, Session] = {}
        self.failures: OrderedDict[str, list[float]] = OrderedDict()
        self.password_hash: str | None = None
        password_file = settings.data_dir / "ui_password"
        if password_file.is_file():
            _protect_secret_file(password_file)
            self.password_hash = password_file.read_text(encoding="ascii").strip()
        elif settings.ui_password:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            password_file.write_text(hash_password(settings.ui_password) + "\n", encoding="ascii")
            _protect_secret_file(password_file)
            self.password_hash = password_file.read_text(encoding="ascii").strip()

    def bearer_valid(self, request: Request) -> bool:
        value = request.headers.get("authorization", "")
        if not value.startswith("Bearer "):
            return False
        return self.token_matches(value[7:].strip())

    def token_matches(self, supplied: str) -> bool:
        """Constant-time match against the current or unexpired previous token."""
        given = supplied.encode("utf-8", "surrogateescape")
        current = hmac.compare_digest(given, self.token.encode())
        previous = bool(
            self.previous_token
            and self.previous_valid_until is not None
            and self.clock() < self.previous_valid_until
            and hmac.compare_digest(given, self.previous_token.encode())
        )
        return current or previous

    def rotate_api_token(self, grace_seconds: int) -> tuple[str, int | None]:
        previous_valid_until = int(self.clock()) + grace_seconds if grace_seconds else None
        old = self.token
        self.token = secrets.token_urlsafe(32)
        self.secret_holder.current = self.token
        self.secret_holder.previous = old if previous_valid_until is not None else None
        atomic_write_secret(token_path(self.settings), self.token + "\n")
        self.previous_token = old if previous_valid_until is not None else None
        self.previous_valid_until = previous_valid_until
        grace_path = self.settings.data_dir / "api_token_grace"
        if self.previous_token is None:
            with suppress(FileNotFoundError):
                grace_path.unlink()
        else:
            atomic_write_secret(
                grace_path,
                json.dumps({"token": self.previous_token, "valid_until": previous_valid_until})
                + "\n",
            )
        return self.token, previous_valid_until

    def revoke_sessions(self, keep: str | None = None) -> None:
        self.sessions = {keep: self.sessions[keep]} if keep in self.sessions else {}

    def change_password(self, new_password: str) -> None:
        path = self.settings.data_dir / "ui_password"
        atomic_write_secret(path, hash_password(new_password) + "\n")
        self.password_hash = path.read_text(encoding="ascii").strip()

    def password_attempt_allowed(self, ip: str) -> bool:
        now = self.clock()
        attempts = [item for item in self.failures.get(f"password:{ip}", []) if now - item < 900]
        self.failures[f"password:{ip}"] = attempts
        return len(attempts) < 4

    def record_password_failure(self, ip: str) -> None:
        self.failures.setdefault(f"password:{ip}", []).append(self.clock())

    def clear_password_failures(self, ip: str) -> None:
        self.failures.pop(f"password:{ip}", None)

    def ingress_valid(self, request: Request) -> bool:
        return bool(
            self.settings.addon_mode
            and request.client is not None
            and request.client.host == "172.30.32.2"
            and request.headers.get("x-ingress-path")
        )

    def session_valid(self, request: Request) -> Session | None:
        sid = request.cookies.get("tonewatch_session")
        session = self.sessions.get(sid or "")
        if session is None or self.clock() - session.last_used > 12 * 3600:
            return None
        session.last_used = self.clock()
        return session

    def authorize(self, request: Request, *, state_changing: bool = False) -> str:
        if self.bearer_valid(request):
            return "bearer"
        if self.ingress_valid(request):
            return "ingress"
        session = self.session_valid(request)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
            )
        if state_changing and request.headers.get("x-csrf-token") != session.csrf:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if state_changing and request.cookies.get("tonewatch_csrf") != session.csrf:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return "session"

    def check_login(self, ip: str, password: str) -> tuple[str, str]:
        now = self.clock()
        attempts = [item for item in self.failures.get(ip, []) if now - item < 900]
        self.failures[ip] = attempts
        self.failures.move_to_end(ip, last=True)
        if len(attempts) >= 5:
            raise HTTPException(
                status_code=429, detail="too many login attempts", headers={"Retry-After": "900"}
            )
        if self.password_hash is None or not verify_password(password, self.password_hash):
            attempts.append(now)
            while len(self.failures) > 1024:
                self.failures.popitem(last=False)
            raise HTTPException(status_code=401, detail="invalid credentials")
        self.failures.pop(ip, None)
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[sid] = Session(csrf, now)
        return sid, csrf
