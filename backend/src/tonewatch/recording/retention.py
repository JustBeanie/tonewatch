"""Safe age, size, and count based recording retention."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import CadIncident, Call, CallCadIncident, DiscoveredTone, Recording


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    max_age_days: int | None = 90
    max_total_bytes: int | None = 5 * 1024**3
    max_count: int | None = None
    orphan_safety_age_seconds: int = 3600
    drill_retention_hours: float = 24


@dataclass(frozen=True, slots=True)
class OrphanScan:
    """Candidates found by one consistent orphan scan."""

    files: tuple[Path, ...]
    missing_rows: tuple[Recording, ...]
    invalid_row_ids: tuple[int, ...]
    file_bytes: int

    @property
    def file_count(self) -> int:
        return len(self.files)


def scan_orphans(
    root: Path,
    rows: list[Recording],
    now: float,
    safety_age: float,
) -> OrphanScan:
    """Find only stable, safe orphan files and old missing rows."""
    resolved_root = root.resolve()
    cutoff = now - safety_age
    known: set[Path] = set()
    missing: list[Recording] = []
    invalid: list[int] = []
    for row in rows:
        try:
            safe = safe_recording_path(resolved_root, Path(row.path))
        except ValueError:
            invalid.append(row.id)
            continue
        known.add(safe)
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if not safe.is_file() and created_at.timestamp() <= cutoff:
            missing.append(row)
    files: list[Path] = []
    file_bytes = 0
    if resolved_root.is_dir():
        for directory, dirnames, filenames in os.walk(resolved_root, followlinks=False):
            dirnames[:] = [name for name in dirnames if not (Path(directory) / name).is_symlink()]
            for name in filenames:
                path = Path(directory) / name
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or name.startswith(".")
                    or name.endswith(".tmp")
                ):
                    continue
                safe = safe_recording_path(resolved_root, path)
                if safe in known or safe.stat().st_mtime > cutoff:
                    continue
                files.append(safe)
                file_bytes += safe.stat().st_size
    return OrphanScan(tuple(files), tuple(missing), tuple(invalid), file_bytes)


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    """The immutable set of rows and files selected by retention policy."""

    recording_ids: tuple[int, ...]
    recording_paths: tuple[Path, ...]
    recording_bytes: int
    call_ids: tuple[Any, ...]
    cad_ids: tuple[tuple[str, str], ...]
    discovered_ids: tuple[int, ...] = ()
    discovered_paths: tuple[Path, ...] = ()
    drill_call_ids: tuple[Any, ...] = ()

    @property
    def counts(self) -> dict[str, object]:
        return {
            "recordings": {"files": len(self.recording_ids), "bytes": self.recording_bytes},
            "calls": len(self.call_ids),
            "cad_incidents": len(self.cad_ids),
            "discovered": len(self.discovered_ids),
            "drills": len(self.drill_call_ids),
        }


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
        self.lock = asyncio.Lock()

    async def plan(self, session: AsyncSession) -> RetentionPlan:
        """Compute retention selections without changing the database or filesystem."""
        result = await session.scalars(select(Recording).order_by(Recording.id))
        rows = list(result.all())
        result.close()
        cad_result = await session.scalars(select(CadIncident))
        cad_rows = list(cad_result.all())
        cad_result.close()
        cutoff = (
            datetime.fromtimestamp(self.clock(), UTC) - timedelta(days=self.policy.max_age_days)
            if self.policy.max_age_days is not None
            else None
        )
        total = sum(row.size_bytes for row in rows)
        selected: list[Recording] = []
        drill_cutoff = datetime.fromtimestamp(self.clock(), UTC) - timedelta(
            hours=self.policy.drill_retention_hours
        )
        drill_result = await session.scalars(select(Call).where(Call.drill.is_(True)))
        drill_rows = list(drill_result.all())
        drill_selected = tuple(
            row.id
            for row in drill_rows
            if not row.drill_keep
            and (
                row.started_at.replace(tzinfo=UTC)
                if row.started_at.tzinfo is None
                else row.started_at
            )
            < drill_cutoff
        )
        for row in rows:
            path = Path(row.path)
            safe_recording_path(self.root, path)
            too_old = (
                cutoff is not None and path.exists() and path.stat().st_mtime < cutoff.timestamp()
            )
            over = (
                self.policy.max_total_bytes is not None and total > self.policy.max_total_bytes
            ) or (
                self.policy.max_count is not None
                and len(rows) - len(selected) > self.policy.max_count
            )
            if too_old or over:
                selected.append(row)
                total -= row.size_bytes
            if row.call_id in drill_selected and row not in selected:
                selected.append(row)
                total -= row.size_bytes
        cad_selected_list: list[tuple[str, str]] = []
        for cad_row in cad_rows:
            cad_last_seen = cad_row.last_seen_at
            if cad_last_seen.tzinfo is None:
                cad_last_seen = cad_last_seen.replace(tzinfo=UTC)
            linked = await session.scalar(
                select(
                    exists().where(
                        CallCadIncident.feed_id == cad_row.feed_id,
                        CallCadIncident.incident_id == cad_row.incident_id,
                    )
                )
            )
            if cutoff is not None and cad_last_seen < cutoff and not linked:
                cad_selected_list.append((cad_row.feed_id, cad_row.incident_id))
        cad_selected = tuple(cad_selected_list)
        discovered_result = await session.scalars(
            select(DiscoveredTone)
            .where(DiscoveredTone.status.in_(("new", "dismissed")))
            .order_by(DiscoveredTone.last_seen.asc(), DiscoveredTone.id.asc())
        )
        discovered_rows = list(discovered_result.all())
        discovered_result.close()
        discovered_selected: list[tuple[int, Path]] = []
        for discovered_row in discovered_rows:
            if not discovered_row.best_clip_recording_path:
                continue
            path = Path(discovered_row.best_clip_recording_path)
            expected = (self.root / "discovered" / f"{discovered_row.id}.mp3").resolve()
            try:
                safe = safe_recording_path(self.root, path)
            except ValueError:
                continue
            discovered_last_seen = discovered_row.last_seen
            if discovered_last_seen.tzinfo is None:
                discovered_last_seen = discovered_last_seen.replace(tzinfo=UTC)
            if (
                safe == expected
                and safe.is_file()
                and (
                    (cutoff is not None and discovered_last_seen < cutoff)
                    or total > (self.policy.max_total_bytes or 0)
                )
            ):
                discovered_selected.append((discovered_row.id, safe))
        return RetentionPlan(
            tuple(row.id for row in selected),
            tuple(Path(row.path) for row in selected),
            sum(row.size_bytes for row in selected),
            tuple(dict.fromkeys([*(row.call_id for row in selected), *drill_selected])),
            cad_selected,
            tuple(item[0] for item in discovered_selected),
            tuple(item[1] for item in discovered_selected),
            drill_selected,
        )

    async def apply(self, session: AsyncSession, plan: RetentionPlan) -> dict[str, object]:
        """Apply a previously computed plan and return its stable counts."""
        for path in plan.recording_paths:
            safe_recording_path(self.root, path)
            path.unlink(missing_ok=True)
        for path in plan.discovered_paths:
            path.unlink(missing_ok=True)
        if plan.recording_ids:
            await session.execute(delete(Recording).where(Recording.id.in_(plan.recording_ids)))
        for feed_id, incident_id in plan.cad_ids:
            await session.execute(
                delete(CadIncident).where(
                    CadIncident.feed_id == feed_id, CadIncident.incident_id == incident_id
                )
            )
        if plan.drill_call_ids:
            await session.execute(delete(Call).where(Call.id.in_(plan.drill_call_ids)))
        for discovered_id in plan.discovered_ids:
            await session.execute(delete(DiscoveredTone).where(DiscoveredTone.id == discovered_id))
        await session.commit()
        return plan.counts

    async def enforce(self, session: AsyncSession) -> list[Path]:
        plan = await self.plan(session)
        await self.apply(session, plan)
        return list(plan.recording_paths) + list(plan.discovered_paths)

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
        async with service.lock, session_factory() as session:
            await service.enforce(session)
            await service.enforce_discovered(session)
            await session.close()
        await sleep(86_400)
