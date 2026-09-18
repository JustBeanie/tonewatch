"""Regression tests for M19e maintenance and metrics review findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tonewatch.admin.counters import MetricsCounters
from tonewatch.api.metrics import render_metrics
from tonewatch.recording.retention import scan_orphans

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_m19e_fix_fresh_temp_and_final_files_are_not_orphans(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    root.mkdir()
    (root / ".call.mp3.tmp").write_bytes(b"temporary")
    (root / "call.mp3").write_bytes(b"finalizing")
    scan = scan_orphans(root, [], now=10_000, safety_age=3600)
    assert scan.files == ()


def test_m19e_fix_metrics_counters_are_monotonic_and_typed() -> None:
    counters = MetricsCounters()
    counters.record_detection("tones")
    counters.record_alert_attempt("target", "recording_ready", "success")
    before = render_metrics(
        {},
        configured_target_ids=["target"],
        configured_toneset_ids=["tones"],
        detections=dict(counters.detections),
        alert_attempts=dict(counters.alert_attempts),
    )
    counters.record_detection("tones")
    counters.record_alert_attempt("target", "recording_ready", "success")
    after = render_metrics(
        {},
        configured_target_ids=["target"],
        configured_toneset_ids=["tones"],
        detections=dict(counters.detections),
        alert_attempts=dict(counters.alert_attempts),
    )
    assert 'tonewatch_detections_total{toneset_id="tones"} 1' in before
    assert 'tonewatch_detections_total{toneset_id="tones"} 2' in after
    assert (
        'tonewatch_alert_attempts_total{target_id="target",phase="recording_ready",'
        'outcome="success"} 1' in before
    )
    assert (
        'tonewatch_alert_attempts_total{target_id="target",phase="recording_ready",'
        'outcome="success"} 2' in after
    )
    assert "# TYPE tonewatch_detections_total counter\n" in after
    assert "# TYPE tonewatch_alert_attempts_total counter\n" in after
