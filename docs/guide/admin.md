# Administration

## Credential management

Credential changes are owner operations under `/api/admin/credentials/`. Bearer-token and cookie-session callers may use them; cookie sessions must send both CSRF cookies/header values. HA add-on ingress is accepted for ordinary admin writes, but is deliberately rejected for credential changes because ingress alone is not CSRF protection.

`POST /api/admin/credentials/api-token/rotate` accepts `grace_seconds` from 0 through 86400 (default 3600) and returns the new token exactly once with `previous_valid_until`. The current token works immediately; at most one previous token remains valid during the persisted grace window. A later rotation invalidates that previous token immediately. Store the one-time response securely; tokens are never included in logs or audit details.

`POST /api/admin/credentials/live-secret/rotate` invalidates every issued live URL immediately and closes active listeners. `POST /api/admin/credentials/ui-password` requires the current password and a new password of at least 12 characters. If no password exists, only API-token authentication may set the first password. A successful session change keeps the caller's session and revokes other sessions; a bearer-authenticated change revokes all sessions. Failed checks are rate-limited and audited without password values. `POST /api/admin/credentials/sessions/revoke-all` invalidates every cookie session, including the caller, while bearer authentication remains valid. All credential responses are `Cache-Control: no-store`.

## Health

Authenticated `GET /api/admin/health` reports one entry per source, including the recent feed-health ring (up to 50 transitions), level and squelch state, DSP realtime factor, dropped/late frames, restart count/time, and bounded last error. Service diagnostics include each event-bus subscriber's queue depth, drops, and oldest-event lag. Storage reports recording bytes, free bytes, SQLite and WAL sizes, and a retention forecast. The forecast sums completed recording sizes over their persisted call times and projects that rate into free space; it is `null` when the rate is unknown or zero and is capped at ten years. Outputs expose target identity/type and delivery timestamps/failure counters only; credentials and URLs are never returned. Build information includes version and process uptime.

## Configuration history and transfer

Every successful configuration mutation creates one immutable snapshot in
`$TONEWATCH_DATA/config-history/`; the directory is bounded to the newest 100
versions (including the startup baseline). Snapshot files contain the complete configuration, including secrets,
so protect the data directory and its backups like `config.yaml`. Files are
written atomically and owner-readable on POSIX systems. The authenticated
`GET /api/admin/config/versions` and version detail/diff endpoints expose only
metadata or masked values. A changed secret is represented as `changed` in a
diff and is never returned.

`POST /api/admin/config/versions/{id}/rollback` requires the current `If-Match`
ETag and uses the normal validation and hot-apply path; rollback creates a new
history version. `GET /api/admin/config/export?format=yaml|json` returns a
no-store attachment with secrets masked by default; secret parameters on GET
are rejected. `POST /api/admin/config/export` accepts `format`,
`include_secrets`, and `confirm`; plaintext export requires
`include_secrets=true` and `confirm=include-secrets`, bearer or a CSRF-protected
session request (Supervisor ingress is rejected), and is audited with a warning
header.

`POST /api/admin/config/import/preview` validates a YAML or JSON document and
returns a masked structured diff without writing. The apply endpoint additionally
requires `If-Match` and uses the normal save path. Safe YAML loading rejects
Python object tags. The `[REDACTED]` placeholder restores the corresponding
stored secret; it is rejected when no stored value exists. Imports are capped at
256 KiB.

Disk scans run in a worker and are cached for up to 60 seconds so the API event loop is not blocked.

## Maintenance and Prometheus metrics

Maintenance actions are under `/api/admin/maintenance/` and require the write-authentication
policy (including CSRF for cookie sessions). Retention preview and run-now share one immutable
plan; checkpoint, vacuum, and orphan apply are serialized with retention and each action is
audited. Orphan previews use relative paths below the recordings root and never follow symlinks.
Orphan cleanup ignores dot-prefixed and `.tmp` files and files or rows newer than the configured
orphan safety age (default: 3600 seconds), so recordings still being finalized are protected.

Prometheus is disabled by default. Set `TONEWATCH_METRICS__ENABLED=true` (or `metrics.enabled`
in the settings source) to enable `GET /metrics`. The endpoint accepts only the API bearer token;
cookie sessions and Supervisor ingress are rejected. Labels are limited to configured IDs and
contain no addresses, URLs, or secrets.

Example scrape configuration:

```yaml
scrape_configs:
  - job_name: tonewatch
    scheme: https
    bearer_token_file: /run/secrets/tonewatch_api_token
    static_configs:
      - targets: [tonewatch:8099]
```

## Admin alerts

Operational alerts are disabled by default. Enable `admin_alerts` and select existing alert-target IDs in `targets` to receive these notifications. The defaults are: feed unhealthy for 5 minutes, disk used at 90%, disk forecast under 7 days, 5 consecutive target failures, stuck squelch enabled, and realtime DSP below 1.5x for 300 seconds. `min_interval_s` defaults to 300 seconds per condition and `max_per_hour` defaults to 6 across all conditions.

Conditions are edge-triggered: a firing notification is sent once after its threshold or hysteresis duration is met, and a single `resolved` notification follows when the condition clears. Reminders while a condition remains latched obey both rate limits; dropped reminders are counted and logged. Feed and DSP conditions have hysteresis, while disk, target, and squelch recovery is immediate.

Every operational payload contains `kind: "admin"`, its condition key, state, severity, timestamp, detail, and relevant measurements. MQTT uses `tonewatch/<instance>/admin`, separate from the page-call topic. Admin messages are never sent through page coalescing or call dedupe, and Home Assistant discovery does not create page-like `event` entities for them. Webhook and script targets receive the same `kind` marker. Admin notifications do not create call-linked `AlertAttempt` rows because they do not represent a call; target delivery health remains visible in the health endpoint.

## Delivery log and retry

Authenticated `GET /api/admin/alert-attempts` supports `call_id`, `target_id`, `phase`, `ok`, `since`, and `until` filters. Results use a stable `created_at DESC, id DESC` cursor and a maximum page size of 200.

`POST /api/admin/alert-attempts/{id}/retry` requires the normal write authentication and CSRF token. Only a failed attempt for an existing call and currently configured target can be retried. It performs one sender call using a rebuilt payload marked `retry: true`, bounded by the target timeout, and records exactly one retry row plus an audit event. A succeeded attempt, missing call, or removed target returns `409`; an unknown attempt returns `404`; an already-running retry returns `429`. Meshtastic rate-limit drops are recorded as `rate_limited`.
