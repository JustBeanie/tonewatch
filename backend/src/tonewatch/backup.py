"""Safe, portable backup archives for the ToneWatch data directory."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable

from tonewatch import __version__
from tonewatch.recording.retention import safe_recording_path

FORMAT_VERSION = 1
ALEMBIC_HEAD = "0008_recording_created_at"
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_CREDENTIAL_FILES = ("api_token", "api_token_grace", "ui_password", "live_stream_secret")


class BackupError(ValueError):
    """A backup failed validation or could not be safely applied."""


def _reject(message: str) -> NoReturn:
    """Raise a detailed validation error without coupling callers to exception text rules."""
    raise BackupError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _online_copy(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def _recording_files(root: Path) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []
    files: list[tuple[str, Path]] = []
    resolved_root = root.resolve()
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        relative = candidate.relative_to(root)
        if any(part.startswith(".") or part.endswith(".tmp") for part in relative.parts):
            continue
        try:
            safe = safe_recording_path(resolved_root, candidate)
        except ValueError:
            continue
        files.append((PurePosixPath("recordings", *relative.parts).as_posix(), safe))
    return files


def create_archive(
    data_dir: Path,
    *,
    include_recordings: bool,
    include_credentials: bool,
    recording_root: Path | None = None,
    output: Path | None = None,
) -> Path:
    """Build a gzip-compressed tar archive, using SQLite's online backup API."""
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    if output is None:
        fd, name = tempfile.mkstemp(prefix="tonewatch-backup-", suffix=".tar.gz", dir=data_dir)
        os.close(fd)
        output = Path(name)
    output = output.resolve()
    with tempfile.TemporaryDirectory(prefix=".backup-build-", dir=data_dir) as temporary:
        staging = Path(temporary)
        db_copy = staging / "tonewatch.db"
        source_db = data_dir / "tonewatch.db"
        if not source_db.is_file():
            _reject("database file does not exist")
        _online_copy(source_db, db_copy)
        payload: list[tuple[str, Path]] = [
            ("config.yaml", data_dir / "config.yaml"),
            ("tonewatch.db", db_copy),
        ]
        if not payload[0][1].is_file():
            _reject("config.yaml does not exist")
        if include_recordings:
            payload.extend(_recording_files(recording_root or data_dir / "recordings"))
        if include_credentials:
            payload.extend(
                (name, data_dir / name) for name in _CREDENTIAL_FILES if (data_dir / name).is_file()
            )
            history = data_dir / "config-history"
            if history.is_dir():
                payload.extend(
                    (
                        PurePosixPath(
                            "config-history", *item.relative_to(history).parts
                        ).as_posix(),
                        item,
                    )
                    for item in sorted(history.rglob("*"))
                    if item.is_file() and not item.is_symlink()
                )
        entries = [
            {"path": name, "size": path.stat().st_size, "sha256": _sha256(path)}
            for name, path in payload
        ]
        manifest: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "tonewatch_version": __version__,
            "alembic_revision": ALEMBIC_HEAD,
            "created_at": datetime.now(UTC).isoformat(),
            "include_recordings": include_recordings,
            "include_credentials": include_credentials,
            "files": entries,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        with tarfile.open(output, "w:gz") as archive:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            archive.addfile(info, io.BytesIO(manifest_bytes))
            for name, path in payload:
                archive.add(path, arcname=name, recursive=False)
    if output.stat().st_size > MAX_ARCHIVE_BYTES:
        output.unlink(missing_ok=True)
        _reject("backup archive exceeds the size limit")
    return output


def _member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _reject(f"unsafe archive member: {name}")
    return path


def _revision_number(value: str) -> int:
    try:
        return int(value.split("_", 1)[0])
    except (ValueError, IndexError):
        _reject(f"unknown Alembic revision: {value}")


def _known_revisions() -> set[str]:
    versions = Path(__file__).parent / "storage" / "migrations" / "versions"
    revisions: set[str] = set()
    for path in versions.glob("*.py"):
        match = re.search(
            r'^revision\s*=\s*["\']([^"\']+)',
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            revisions.add(match.group(1))
    revisions.add(ALEMBIC_HEAD)
    return revisions


def _verified_members(  # noqa: PLR0912, PLR0915 -- each branch is an independent archive invariant.
    archive: tarfile.TarFile,
) -> tuple[dict[str, Any], list[tarfile.TarInfo]]:
    members = archive.getmembers()
    if any(member.name == "manifest.json" for member in members) is False:
        _reject("archive has no manifest")
    manifest_member = next(member for member in members if member.name == "manifest.json")
    if not manifest_member.isfile() or manifest_member.size > MAX_MEMBER_BYTES:
        _reject("invalid manifest")
    raw = archive.extractfile(manifest_member)
    if raw is None:
        _reject("invalid manifest")
    try:
        manifest = json.loads(raw.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _reject(f"invalid manifest JSON: {exc}")
    if manifest.get("format_version") != FORMAT_VERSION:
        _reject("unknown backup format version")
    revision = str(manifest.get("alembic_revision", ""))
    if revision not in _known_revisions():
        _reject(f"unknown Alembic revision: {revision}")
    if _revision_number(revision) > _revision_number(ALEMBIC_HEAD):
        _reject("backup was created by a newer database schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        _reject("manifest files are invalid")
    expected: dict[str, dict[str, Any]] = {}
    for item in files:
        name = str(item.get("path", ""))
        _member_path(name)
        if (
            name in expected
            or not isinstance(item.get("size"), int)
            or not isinstance(item.get("sha256"), str)
        ):
            _reject("manifest files are invalid")
        expected[name] = item
    actual = {member.name for member in members if member.name != "manifest.json"}
    if actual != set(expected):
        _reject("archive members do not match the manifest")
    if "config.yaml" not in expected or "tonewatch.db" not in expected:
        _reject("archive is missing required files")
    total = 0
    verified: list[tarfile.TarInfo] = []
    for member in members:
        if member.name == "manifest.json":
            continue
        _member_path(member.name)
        if not member.isfile() or member.islnk() or member.issym() or member.isdev():
            _reject(f"archive member is not a regular file: {member.name}")
        if member.size > MAX_MEMBER_BYTES:
            _reject("archive member exceeds the size limit")
        total += member.size
        if total > MAX_ARCHIVE_BYTES:
            _reject("archive uncompressed size exceeds the limit")
        source = archive.extractfile(member)
        if source is None:
            _reject(f"cannot read archive member: {member.name}")
        digest = hashlib.sha256()
        for chunk in iter(source.read, b""):
            digest.update(chunk)
        if (
            digest.hexdigest() != expected[member.name]["sha256"]
            or member.size != expected[member.name]["size"]
        ):
            _reject(f"checksum mismatch: {member.name}")
        verified.append(member)
    return manifest, verified


def restore_archive(  # noqa: PLR0912, PLR0915 -- transaction branches each protect an owned path invariant.
    archive_path: Path,
    data_dir: Path,
    *,
    dry_run: bool = False,
    recording_root: Path | None = None,
    post_apply: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Verify and, unless dry-run, atomically apply an archive with rollback."""
    data_dir = data_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        manifest, members = _verified_members(archive)
        summary = {
            "format_version": manifest["format_version"],
            "files": len(members),
            "alembic_revision": manifest["alembic_revision"],
            "include_recordings": manifest["include_recordings"],
        }
        if dry_run:
            return summary
        data_dir.mkdir(parents=True, exist_ok=True)
        recording_root = (recording_root or data_dir / "recordings").resolve()
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=data_dir))
        try:
            for member in members:
                destination = staging / Path(*PurePosixPath(member.name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    _reject(f"cannot read archive member: {member.name}")
                with destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            moved = data_dir / f"pre-restore-{timestamp}"
            while moved.exists():
                timestamp += "-1"
                moved = data_dir / f"pre-restore-{timestamp}"
            moved.mkdir()
            member_names = {member.name for member in members}
            owned: list[tuple[Path, Path]] = [
                (data_dir / name, Path(name))
                for name in ("config.yaml", "tonewatch.db", "tonewatch.db-wal", "tonewatch.db-shm")
                if name in member_names or name.startswith("tonewatch.db-")
            ]
            owned.extend(
                (data_dir / name, Path(name)) for name in _CREDENTIAL_FILES if name in member_names
            )
            if any(name.startswith("config-history/") for name in member_names):
                owned.append((data_dir / "config-history", Path("config-history")))
            if bool(manifest["include_recordings"]):
                owned.append((recording_root, Path("recordings")))
            for source_path, relative in owned:
                if source_path.exists():
                    destination = moved / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source_path), destination)
            destinations = [source for source, _ in owned]
            try:
                for item in staging.iterdir():
                    destination = (
                        recording_root if item.name == "recordings" else data_dir / item.name
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(item), destination)
                if post_apply is not None and manifest["alembic_revision"] != ALEMBIC_HEAD:
                    post_apply()
            except Exception:
                for destination in destinations:
                    if destination.exists():
                        shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                for item in moved.iterdir():
                    destination = (
                        recording_root if item.name == "recordings" else data_dir / item.name
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(item), destination)
                raise
            return summary
        finally:
            shutil.rmtree(staging, ignore_errors=True)
