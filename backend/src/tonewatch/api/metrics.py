"""Dependency-free Prometheus exposition for bounded ToneWatch health data."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tonewatch.alerts.phases import ALERT_METRIC_PHASES


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _line(name: str, value: object, labels: dict[str, object] | None = None) -> str:
    suffix = ""
    if labels:
        suffix = "{" + ",".join(f'{key}="{_escape(item)}"' for key, item in labels.items()) + "}"
    return f"{name}{suffix} {value}\n"


def render_metrics(
    snapshot: dict[str, Any],
    *,
    configured_source_ids: Iterable[str] = (),
    configured_target_ids: Iterable[str] = (),
    configured_toneset_ids: Iterable[str] = (),
    configured_feed_ids: Iterable[str] = (),
    version: str = "unknown",
    detections: dict[str, int] | None = None,
    alert_attempts: dict[tuple[str, str, str], int] | None = None,
    db_size: int = 0,
) -> str:
    """Render only configured identifiers and scalar health values."""
    sources = {str(item["id"]): item for item in snapshot.get("sources", [])}
    targets = set(configured_target_ids)
    tonesets = set(configured_toneset_ids)
    feeds = set(configured_feed_ids)
    lines: list[str] = []
    metric_types = {
        "tonewatch_detections_total": "counter",
        "tonewatch_alert_attempts_total": "counter",
        "tonewatch_feed_healthy": "gauge",
        "tonewatch_realtime_factor": "gauge",
        "tonewatch_frames_dropped_total": "counter",
        "tonewatch_eventbus_queue_depth": "gauge",
        "tonewatch_disk_free_bytes": "gauge",
        "tonewatch_db_size_bytes": "gauge",
        "tonewatch_cad_feed_connected": "gauge",
        "tonewatch_build_info": "gauge",
    }
    for name, kind in metric_types.items():
        lines.extend(
            (
                f"# HELP {name} ToneWatch {name.removeprefix('tonewatch_')}\n",
                f"# TYPE {name} {kind}\n",
            )
        )
    lines.extend(
        _line(
            "tonewatch_detections_total",
            (detections or {}).get(toneset_id, 0),
            {"toneset_id": toneset_id},
        )
        for toneset_id in sorted(tonesets)
    )
    for (target_id, phase, outcome), count in sorted((alert_attempts or {}).items()):
        if (
            target_id in targets
            and phase in ALERT_METRIC_PHASES
            and outcome in {"success", "failure", "rate_limited"}
        ):
            lines.append(
                _line(
                    "tonewatch_alert_attempts_total",
                    count,
                    {"target_id": target_id, "phase": phase, "outcome": outcome},
                )
            )
    for source_id in sorted(set(configured_source_ids)):
        item = sources.get(source_id, {})
        healthy = (
            bool(item.get("feed_health_history", [{}])[-1].get("healthy", False))
            if item.get("feed_health_history")
            else False
        )
        lines.extend(
            (
                _line("tonewatch_feed_healthy", int(healthy), {"source_id": source_id}),
                _line(
                    "tonewatch_realtime_factor",
                    item.get("realtime_factor") if item.get("realtime_factor") is not None else 0,
                    {"source_id": source_id},
                ),
                _line(
                    "tonewatch_frames_dropped_total",
                    item.get("dropped_frames") or 0,
                    {"source_id": source_id},
                ),
            )
        )
    lines.extend(
        _line(
            "tonewatch_eventbus_queue_depth",
            subscriber.get("depth", 0),
            {"subscriber": str(subscriber.get("id", "unknown"))},
        )
        for subscriber in snapshot.get("service", {}).get("subscribers", [])
    )
    storage = snapshot.get("storage", {})
    lines.append(_line("tonewatch_disk_free_bytes", storage.get("free_bytes", 0)))
    lines.append(_line("tonewatch_db_size_bytes", db_size or storage.get("db_bytes", 0)))
    cad = {str(item["id"]): item for item in snapshot.get("cad_feeds", [])}
    lines.extend(
        _line(
            "tonewatch_cad_feed_connected",
            int(bool(cad.get(feed_id, {}).get("connected", False))),
            {"feed_id": feed_id},
        )
        for feed_id in sorted(feeds)
    )
    lines.append(_line("tonewatch_build_info", 1, {"version": version}))
    return "".join(lines)
