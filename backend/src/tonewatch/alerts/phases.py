"""Alert delivery phases shared by dispatch and operational metrics."""

ALERT_METRIC_PHASES = frozenset(
    {"pre_alert", "recording_ready", "retry", "unknown", "call_enriched", "closed"}
)
