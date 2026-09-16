# Administration

## Health

Authenticated `GET /api/admin/health` reports one entry per source, including the recent feed-health ring (up to 50 transitions), level and squelch state, DSP realtime factor, dropped/late frames, restart count/time, and bounded last error. Service diagnostics include each event-bus subscriber's queue depth, drops, and oldest-event lag. Storage reports recording bytes, free bytes, SQLite and WAL sizes, and a retention forecast. The forecast sums completed recording sizes over their persisted call times and projects that rate into free space; it is `null` when the rate is unknown or zero and is capped at ten years. Outputs expose target identity/type and delivery timestamps/failure counters only; credentials and URLs are never returned. Build information includes version and process uptime.

Disk scans run in a worker and are cached for up to 60 seconds so the API event loop is not blocked.

## Delivery log and retry

Authenticated `GET /api/admin/alert-attempts` supports `call_id`, `target_id`, `phase`, `ok`, `since`, and `until` filters. Results use a stable `created_at DESC, id DESC` cursor and a maximum page size of 200.

`POST /api/admin/alert-attempts/{id}/retry` requires the normal write authentication and CSRF token. Only a failed attempt for an existing call and currently configured target can be retried. It performs one sender call using a rebuilt payload marked `retry: true`, bounded by the target timeout, and records exactly one retry row plus an audit event. A succeeded attempt, missing call, or removed target returns `409`; an unknown attempt returns `404`; an already-running retry returns `429`. Meshtastic rate-limit drops are recorded as `rate_limited`.
