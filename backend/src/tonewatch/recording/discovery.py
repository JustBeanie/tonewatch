"""Evidence clip helpers for auto-discovered tone clusters."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from tonewatch.recording.encoder import AudioEncoder
from tonewatch.recording.retention import safe_recording_path

if TYPE_CHECKING:
    from datetime import datetime

    import numpy as np


def discovery_clip_path(root: Path, cluster_id: int) -> Path:
    """Return the only permitted path for a cluster's evidence clip."""
    if cluster_id < 1:
        raise ValueError("cluster id must be positive")
    directory = root.resolve() / "discovered"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cluster_id}.mp3"
    safe_recording_path(root, path)
    return path


def replace_discovery_clip(root: Path, cluster_id: int, encoded: bytes) -> Path:
    """Write a cluster clip atomically, replacing only that cluster's own file."""
    path = discovery_clip_path(root, cluster_id)
    fd, temporary = tempfile.mkstemp(prefix=f".{cluster_id}.", suffix=".mp3", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        safe_recording_path(root, temporary_path)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def encode_discovery_clip(
    root: Path,
    cluster_id: int,
    samples: np.ndarray,
    *,
    call_start: datetime,
    source_id: str,
) -> Path:
    """Encode a discovery window and atomically replace that cluster's clip."""
    path = discovery_clip_path(root, cluster_id)
    fd, temporary = tempfile.mkstemp(prefix=f".{cluster_id}.", suffix=".mp3.tmp", dir=path.parent)
    temporary_path = Path(temporary)
    os.close(fd)
    try:
        AudioEncoder(root).encode_samples_to_path(
            temporary_path,
            samples,
            fmt="mp3",
            title=f"Discovered tone {cluster_id} {call_start.isoformat()}",
            toneset_ids=frozenset(),
            source_id=source_id,
            call_id=f"discovery-{cluster_id}",
        )
        encoded = temporary_path.read_bytes()
        return replace_discovery_clip(root, cluster_id, encoded)
    finally:
        temporary_path.unlink(missing_ok=True)
