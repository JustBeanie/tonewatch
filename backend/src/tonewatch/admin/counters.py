"""Process-lifetime monotonic counters exported as Prometheus counters."""

from __future__ import annotations

from collections import Counter


class MetricsCounters:
    """Process-lifetime monotonic counters for Prometheus counter metrics."""

    def __init__(self) -> None:
        """Start every counter at zero for this process."""
        self.detections: Counter[str] = Counter()
        self.alert_attempts: Counter[tuple[str, str, str]] = Counter()

    def record_detection(self, toneset_id: str) -> None:
        """Count one persisted tone-set detection."""
        self.detections[toneset_id] += 1

    def record_alert_attempt(self, target_id: str, phase: str, outcome: str) -> None:
        """Count one persisted alert attempt."""
        self.alert_attempts[(target_id, phase, outcome)] += 1


METRICS_COUNTERS = MetricsCounters()
