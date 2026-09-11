"""Safe age, size, and count based recording retention."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tonewatch.storage.models import Recording


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    max_age_days: int | None = 90
    max_total_bytes: int | None = 5 * 1024**3
    max_count: int | None = None


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

    async def enforce(self, session: AsyncSession) -> list[Path]:
        rows = list((await session.scalars(select(Recording).order_by(Recording.id))).all())
        total = sum(row.size_bytes for row in rows)
        removed: list[Path] = []
        cutoff = (
            datetime.fromtimestamp(self.clock(), UTC) - timedelta(days=self.policy.max_age_days)
            if self.policy.max_age_days is not None
            else None
        )
        for index, row in enumerate(rows):
            path = Path(row.path)
            too_old = (
                cutoff is not None and path.exists() and path.stat().st_mtime < cutoff.timestamp()
            )
            over = (
                self.policy.max_total_bytes is not None and total > self.policy.max_total_bytes
            ) or (self.policy.max_count is not None and len(rows) - index > self.policy.max_count)
            if not (too_old or over):
                continue
            resolved = path.resolve(strict=False)
            if path.is_symlink() or (resolved != self.root and self.root not in resolved.parents):
                raise ValueError(f"refusing recording path outside recordings root: {path}")
            path.unlink(missing_ok=True)
            await session.execute(delete(Recording).where(Recording.id == row.id))
            total -= row.size_bytes
            removed.append(path)
        await session.commit()
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
        await sleep(86_400)
