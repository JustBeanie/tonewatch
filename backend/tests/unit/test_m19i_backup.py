"""M19i backup archive contracts, written before the implementation."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sqlite3
import tarfile
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from tonewatch.api.app import create_app
from tonewatch.api.routes import backup as backup_routes
from tonewatch.backup import FORMAT_VERSION, create_archive, restore_archive
from tonewatch.instance_lock import InstanceRunningError, acquire_instance_lock
from tonewatch.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path


def test_online_backup_excludes_uncommitted_rows(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = tmp_path / "tonewatch.db"
    connection = sqlite3.connect(database)
    connection.execute("create table calls (id integer primary key, value text)")
    connection.execute("insert into calls(value) values ('committed')")
    connection.commit()
    writer = sqlite3.connect(database)
    writer.execute("pragma journal_mode=wal")
    writer.execute("begin")
    writer.execute("insert into calls(value) values ('uncommitted')")
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    writer.rollback()
    writer.close()
    connection.close()

    restored = tmp_path / "restored"
    restore_archive(archive, restored)
    check = sqlite3.connect(restored / "tonewatch.db")
    assert check.execute("pragma integrity_check").fetchone() == ("ok",)
    assert check.execute("select value from calls order by id").fetchall() == [("committed",)]
    check.close()


def test_archive_round_trip_and_default_secret_exclusion(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.execute("insert into example values ('row')")
    database.commit()
    database.close()
    (tmp_path / "api_token").write_bytes(b"secret")
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
    assert "manifest.json" in names
    assert "api_token" not in names
    restored = tmp_path / "restored"
    restore_archive(archive, restored)
    assert not (restored / "api_token").exists()
    assert (restored / "config.yaml").read_bytes() == b"sources: []\n"


@pytest.mark.parametrize("kind", ["checksum", "extra", "missing", "traversal", "absolute"])
def test_hostile_archive_is_rejected_without_writing(tmp_path: Path, kind: str) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.commit()
    database.close()
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    hostile = tmp_path / f"{kind}.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(hostile, "w:gz") as target:
        for member in source.getmembers():
            if kind == "missing" and member.name == "config.yaml":
                continue
            if kind == "checksum" and member.name == "config.yaml":
                payload = b"changed"
                altered = tarfile.TarInfo(member.name)
                altered.size = len(payload)
                target.addfile(altered, __import__("io").BytesIO(payload))
                continue
            target.addfile(member, source.extractfile(member) if member.isfile() else None)
        if kind == "extra":
            extra = tarfile.TarInfo("extra.txt")
            extra.size = 1
            target.addfile(extra, __import__("io").BytesIO(b"x"))
        if kind in {"traversal", "absolute"}:
            name = "../evil" if kind == "traversal" else "/evil"
            bad = tarfile.TarInfo(name)
            bad.size = 1
            target.addfile(bad, __import__("io").BytesIO(b"x"))
    before = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path != hostile and path.name != "restored"
    )
    with pytest.raises(ValueError):
        restore_archive(hostile, tmp_path / "restored")
    after = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path != hostile and path.name != "restored"
    )
    assert after == before


def test_manifest_format_version_is_public() -> None:
    assert FORMAT_VERSION == 1


def test_restore_replaces_only_owned_paths_and_uses_external_recording_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source_recordings = tmp_path / "source-media"
    source.mkdir()
    source_recordings.mkdir()
    (source / "config.yaml").write_bytes(b"new-config\n")
    database = sqlite3.connect(source / "tonewatch.db")
    database.execute("create table example (value text)")
    database.execute("insert into example values ('new')")
    database.commit()
    database.close()
    (source_recordings / "call.mp3").write_bytes(b"recording")
    archive = create_archive(
        source,
        recording_root=source_recordings,
        include_recordings=True,
        include_credentials=False,
    )

    target = tmp_path / "target"
    target_recordings = tmp_path / "target-media"
    target.mkdir()
    target_recordings.mkdir()
    (target / "config.yaml").write_bytes(b"old-config\n")
    (target / "config-history").mkdir()
    (target / "config-history" / "keep.yaml").write_bytes(b"keep")
    (target / "pre-restore-old").mkdir()
    (target / "pre-restore-old" / "keep.txt").write_bytes(b"keep")
    (target_recordings / "old.mp3").write_bytes(b"keep-recording")
    restore_archive(archive, target, recording_root=target_recordings)
    assert (target / "config.yaml").read_bytes() == b"new-config\n"
    assert (target / "config-history" / "keep.yaml").read_bytes() == b"keep"
    assert (target / "pre-restore-old" / "keep.txt").read_bytes() == b"keep"
    assert not (target_recordings / "old.mp3").exists()
    assert (target_recordings / "call.mp3").read_bytes() == b"recording"


def test_restore_without_recordings_preserves_existing_recordings(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.commit()
    database.close()
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "keep.mp3").write_bytes(b"keep")
    restore_archive(archive, tmp_path)
    assert (recordings / "keep.mp3").read_bytes() == b"keep"


def test_restore_removes_stale_database_wal_and_rollback_is_tree_exact(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.execute("insert into example values ('new')")
    database.commit()
    database.close()
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    (tmp_path / "tonewatch.db-wal").write_bytes(b"stale")
    (tmp_path / "tonewatch.db-shm").write_bytes(b"stale")
    older = _rewrite_revision(archive, tmp_path / "older.tar.gz", "0007_cad_incidents")
    before = _tree_hash(tmp_path)
    with pytest.raises(RuntimeError, match="upgrade failed"):
        restore_archive(
            older,
            tmp_path,
            post_apply=lambda: (_ for _ in ()).throw(RuntimeError("upgrade failed")),
        )
    assert _tree_hash(tmp_path, exclude_prefix="pre-restore-") == before
    assert not list(tmp_path.glob(".restore-*"))
    restore_archive(archive, tmp_path)
    restored_db = sqlite3.connect(tmp_path / "tonewatch.db")
    assert restored_db.execute("select value from example").fetchall() == [("new",)]
    restored_db.close()
    assert not (tmp_path / "tonewatch.db-wal").exists()


def _tree_hash(root: Path, *, exclude_prefix: str = "") -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (exclude_prefix and path.name.startswith(exclude_prefix)) or relative.startswith(
            "pre-restore-"
        ):
            continue
        digest.update(relative.encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _rewrite_revision(archive: Path, output: Path, revision: str) -> Path:
    with tarfile.open(archive, "r:gz") as source, tarfile.open(output, "w:gz") as target:
        manifest_file = source.extractfile("manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read())
        manifest["alembic_revision"] = revision
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        target.addfile(info, io.BytesIO(raw))
        for member in source.getmembers():
            if member.name != "manifest.json":
                target.addfile(member, source.extractfile(member))
    return output


def test_unknown_but_lower_revision_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.commit()
    database.close()
    archive = create_archive(tmp_path, include_recordings=False, include_credentials=False)
    rewritten = tmp_path / "unknown.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(rewritten, "w:gz") as target:
        manifest_file = source.extractfile("manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read())
        manifest["alembic_revision"] = "0005_something_else"
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        target.addfile(info, io.BytesIO(raw))
        for member in source.getmembers():
            if member.name != "manifest.json":
                target.addfile(member, source.extractfile(member))
    with pytest.raises(ValueError, match="unknown Alembic revision"):
        restore_archive(rewritten, tmp_path / "restored")


def test_instance_lock_stale_file_does_not_block(tmp_path: Path) -> None:
    lock_path = tmp_path / "tonewatch.pid.lock"
    lock_path.write_text("stale", encoding="ascii")
    handle = acquire_instance_lock(tmp_path)
    handle.close()


def test_instance_lock_holder_blocks_until_release(tmp_path: Path) -> None:
    first = acquire_instance_lock(tmp_path)
    try:
        with pytest.raises(InstanceRunningError):
            acquire_instance_lock(tmp_path)
    finally:
        first.close()
    second = acquire_instance_lock(tmp_path)
    second.close()


@pytest.mark.asyncio
async def test_app_lifespan_holds_and_releases_instance_lock(tmp_path: Path) -> None:
    class FakeSupervisor:
        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

    app = create_app(
        Settings(data_dir=tmp_path, zeroconf_enabled=False),
        supervisor=FakeSupervisor(),
        session_factory=cast("Any", lambda: None),
    )
    async with app.router.lifespan_context(app):
        with pytest.raises(InstanceRunningError):
            acquire_instance_lock(tmp_path)
    handle = acquire_instance_lock(tmp_path)
    handle.close()


@pytest.mark.asyncio
async def test_backup_api_streams_and_cleans_temp_archive(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_bytes(b"sources: []\n")
    database = sqlite3.connect(tmp_path / "tonewatch.db")
    database.execute("create table example (value text)")
    database.commit()
    database.close()
    app = SimpleNamespace(
        state=SimpleNamespace(
            maintenance_lock=asyncio.Lock(),
            settings=SimpleNamespace(data_dir=tmp_path, recording_path=tmp_path / "recordings"),
            session_factory=None,
        )
    )
    request = cast("Any", SimpleNamespace(app=app, state=SimpleNamespace(auth="bearer")))
    response = await backup_routes.backup(request, backup_routes.BackupRequest())
    assert response.headers["cache-control"] == "no-store"
    chunks = [bytes(cast("bytes", chunk)) async for chunk in response.body_iterator]
    body = b"".join(chunks)
    assert body.startswith(b"\x1f\x8b")
    archives = await asyncio.to_thread(lambda: list(tmp_path.glob(".tonewatch-backup-*.tar.gz")))
    assert not archives
    request.state.auth = "disconnect"
    response = await backup_routes.backup(request, backup_routes.BackupRequest())
    iterator = cast("Any", response.body_iterator)
    await anext(iterator)
    await iterator.aclose()
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob(".tonewatch-backup-*.tar.gz")))
    with pytest.raises(Exception, match="rate limit"):
        await backup_routes.backup(request, backup_routes.BackupRequest())


@pytest.mark.asyncio
async def test_backup_api_refuses_ingress_credentials_and_busy_lock(tmp_path: Path) -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            maintenance_lock=asyncio.Lock(),
            settings=SimpleNamespace(data_dir=tmp_path),
            session_factory=None,
        )
    )
    ingress = cast("Any", SimpleNamespace(app=app, state=SimpleNamespace(auth="ingress")))
    with pytest.raises(Exception, match="not available through ingress"):
        await backup_routes.backup(ingress, backup_routes.BackupRequest(include_credentials=True))
    await app.state.maintenance_lock.acquire()
    try:
        bearer = cast("Any", SimpleNamespace(app=app, state=SimpleNamespace(auth="bearer")))
        with pytest.raises(Exception, match="already running"):
            await backup_routes.backup(bearer, backup_routes.BackupRequest())
    finally:
        app.state.maintenance_lock.release()
