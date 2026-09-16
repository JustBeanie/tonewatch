# Administration

## Health

Authenticated `GET /api/admin/health` reports one entry per source, including the recent feed-health ring (up to 50 transitions), level and squelch state, DSP realtime factor, dropped/late frames, restart count/time, and bounded last error. Service diagnostics include each event-bus subscriber's queue depth, drops, and oldest-event lag. Storage reports recording bytes, free bytes, SQLite and WAL sizes, and a retention forecast. The forecast sums completed recording sizes over their persisted call times and projects that rate into free space; it is `null` when the rate is unknown or zero and is capped at ten years. Outputs expose target identity/type and delivery timestamps/failure counters only; credentials and URLs are never returned. Build information includes version and process uptime.

Disk scans run in a worker and are cached for up to 60 seconds so the API event loop is not blocked.

## Admin alerts

Operational alerts are disabled by default. Enable `admin_alerts` and select existing alert-target IDs in `targets` to receive these notifications. The defaults are: feed unhealthy for 5 minutes, disk used at 90%, disk forecast under 7 days, 5 consecutive target failures, stuck squelch enabled, and realtime DSP below 1.5x for 300 seconds. `min_interval_s` defaults to 300 seconds per condition and `max_per_hour` defaults to 6 across all conditions.

Conditions are edge-triggered: a firing notification is sent once after its threshold or hysteresis duration is met, and a single `resolved` notification follows when the condition clears. Reminders while a condition remains latched obey both rate limits; dropped reminders are counted and logged. Feed and DSP conditions have hysteresis, while disk, target, and squelch recovery is immediate.

Every operational payload contains `kind: "admin"`, its condition key, state, severity, timestamp, detail, and relevant measurements. MQTT uses `tonewatch/<instance>/admin`, separate from the page-call topic. Admin messages are never sent through page coalescing or call dedupe, and Home Assistant discovery does not create page-like `event` entities for them. Webhook and script targets receive the same `kind` marker. Admin notifications do not create call-linked `AlertAttempt` rows because they do not represent a call; target delivery health remains visible in the health endpoint.

## Delivery log and retry

Authenticated `GET /api/admin/alert-attempts` supports `call_id`, `target_id`, `phase`, `ok`, `since`, and `until` filters. Results use a stable `created_at DESC, id DESC` cursor and a maximum page size of 200.

`POST /api/admin/alert-attempts/{id}/retry` requires the normal write authentication and CSRF token. Only a failed attempt for an existing call and currently configured target can be retried. It performs one sender call using a rebuilt payload marked `retry: true`, bounded by the target timeout, and records exactly one retry row plus an audit event. A succeeded attempt, missing call, or removed target returns `409`; an unknown attempt returns `404`; an already-running retry returns `429`. Meshtastic rate-limit drops are recorded as `rate_limited`.
