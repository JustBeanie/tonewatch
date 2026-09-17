"""Safe age, size, and count based recording retention."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import CadIncident, CallCadIncident, DiscoveredTone, Recording


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    max_age_days: int | None = 90
    max_total_bytes: int | None = 5 * 1024**3
    max_count: int | None = None


def safe_recording_path(root: Path, path: Path) -> Path:
    """Resolve a recording path and reject symlinks or paths outside the root."""
    resolved_root = root.resolve()
    resolved = path.resolve(strict=False)
    if path.is_symlink() or resolved == resolved_root or resolved_root not in resolved.parents:
        raise ValueError(f"refusing recording path outside recordings root: {path}")
    return resolved


class RetentionService:
    def __init__(
        self,
        recordings_root: Path,
        policy: RetentionPolicy,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = recordings_root.resolve()
        self.policy, self.clock = policy, clock

    async def enforce(self, session: AsyncSession) -> list[Path]:  # noqa: PLR0915 -- retention coordinates two bounded file classes.
        result = await session.scalars(select(Recording).order_by(Recording.id))
        rows = list(result.all())
        result.close()
        discovered_result = await session.scalars(
            select(DiscoveredTone)
            .where(DiscoveredTone.status.in_(("new", "dismissed")))
            .order_by(DiscoveredTone.last_seen.asc(), DiscoveredTone.id.asc())
        )
        discovered_rows = list(discovered_result.all())
        discovered_result.close()
        discovered_files: list[tuple[DiscoveredTone, Path, int]] = []
        for row in discovered_rows:
            if not row.best_clip_recording_path:
                continue
            path = Path(row.best_clip_recording_path)
            expected = self.root / "discovered" / f"{row.id}.mp3"
            try:
                safe = safe_recording_path(self.root, path)
            except ValueError:
                continue
            if safe != expected.resolve() or not safe.is_file():
                continue
            discovered_files.append((row, safe, safe.stat().st_size))
        total = sum(row.size_bytes for row in rows) + sum(size for _, _, size in discovered_files)
        item_count = len(rows) + len(discovered_files)
        removed: list[Path] = []
        cutoff = (
            datetime.fromtimestamp(self.clock(), UTC) - timedelta(days=self.policy.max_age_days)
            if self.policy.max_age_days is not None
            else None
        )
        if cutoff is not None:
            await session.execute(
                delete(CadIncident).where(
                    CadIncident.last_seen_at < cutoff,
                    ~exists(
                        select(CallCadIncident.call_id).where(
                            CallCadIncident.feed_id == CadIncident.feed_id,
                            CallCadIncident.incident_id == CadIncident.incident_id,
                        )
                    ),
                )
            )
        for recording in rows:
            path = Path(recording.path)
            too_old = (
                cutoff is not None and path.exists() and path.stat().st_mtime < cutoff.timestamp()
            )
            over = (
                self.policy.max_total_bytes is not None and total > self.policy.max_total_bytes
            ) or (self.policy.max_count is not None and item_count > self.policy.max_count)
            if not (too_old or over):
                continue
            safe_recording_path(self.root, path)
            path.unlink(missing_ok=True)
            await session.execute(delete(Recording).where(Recording.id == recording.id))
            total -= recording.size_bytes
            item_count -= 1
            removed.append(path)
        for row, path, size in discovered_files:
            too_old = cutoff is not None and path.stat().st_mtime < cutoff.timestamp()
            over = (
                self.policy.max_total_bytes is not None and total > self.policy.max_total_bytes
            ) or (self.policy.max_count is not None and item_count > self.policy.max_count)
            if not (too_old or over):
                continue
            path.unlink(missing_ok=True)
            row.best_clip_recording_path = None
            total -= size
            item_count -= 1
            removed.append(path)
        commit_task = asyncio.create_task(session.commit(), name="tonewatch-retention-commit")
        try:
            await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            await commit_task
            raise
        directories = {
            parent
            for path in removed
            for parent in (path.parent, *path.parent.parents)
            if self.root in parent.parents and parent != self.root
        }
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            if directory != self.root and directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    async def enforce_discovered(self, session: AsyncSession, *, cap: int = 1000) -> list[Path]:
        """Prune oldest unseen discovery clusters and only their own clips."""
        result = await session.scalars(
            select(DiscoveredTone)
            .where(DiscoveredTone.status.in_(("new", "dismissed")))
            .order_by(DiscoveredTone.last_seen.asc(), DiscoveredTone.id.asc())
        )
        rows = list(result.all())
        result.close()
        removed: list[Path] = []
        for row in rows[: max(0, len(rows) - cap)]:
            if row.best_clip_recording_path:
                path = Path(row.best_clip_recording_path)
                try:
                    safe = safe_recording_path(self.root, path)
                    expected = (self.root / "discovered" / f"{row.id}.mp3").resolve()
                    if safe == expected:
                        safe.unlink(missing_ok=True)
                        removed.append(safe)
                except ValueError:
                    pass
            await session.delete(row)
        if rows and len(rows) > cap:
            commit_task = asyncio.create_task(
                session.commit(), name="tonewatch-discovery-retention-commit"
            )
            await asyncio.shield(commit_task)
        return removed


async def retention_loop(
    service: RetentionService,
    session_factory: Callable[[], Any],
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Run immediately, then once per day; both clock and sleep are injectable."""
    while True:
        async with session_factory() as session:
            await service.enforce(session)
            await service.enforce_discovered(session)
            await session.close()
        await sleep(86_400)
