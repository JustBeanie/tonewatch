# ADR 0009: Home Assistant add-on runtime

## Status

Accepted for the app-side M10a work. Real Home Assistant verification remains
`PENDING-HIL`.

## Context

The add-on runs the same image as the Docker deployment. Supervisor exposes
`SUPERVISOR_TOKEN`, `/data/options.json`, the `/media` mapping, MQTT service
credentials, and the add-on audio/device mappings. The MQTT service credentials
rotate, so storing them in `config.yaml`, SQLite, audit rows, logs, API output,
or discovery configuration would create stale secrets and an avoidable
disclosure path.

## Decisions

### Options and public recording URLs

The app reads the fixed add-on keys `log_level`, `public_base_url`, `mqtt_mode`,
and `ui_password` explicitly. Unknown keys are ignored after a structured warning
that contains only their names. Environment variables take precedence over
add-on options, and add-on options take precedence over defaults. There is no
`settings` section in the current `config.yaml` schema.

`public_base_url` accepts only `http` and `https` URLs without userinfo, query,
or fragment, and its trailing slash is normalized away. If set, alert payloads
use an absolute recording URL. If unset, they retain `/api/recordings/{id}` and
include `recording_path_relative: true`.

An HA ingress URL is not a usable `public_base_url`: it requires an HA session
when fetched by an external webhook, MQTT consumer, or notification. Add-on
users should set the direct host and port if they expose one, or rely on the
authenticated proxy supplied by the M11 integration.

### Supervisor MQTT

`source: supervisor` is a persisted target marker. In add-on mode and
`mqtt_mode: supervisor`, the publisher fetches
`GET http://supervisor/services/mqtt` with the bearer token immediately before
each connection. Host, port, TLS, protocol, username, and password remain in
memory for that connection only, so reconnects observe rotated credentials.
`mqtt_mode: manual` never creates a target, and `mqtt_mode: off` leaves targets
in the YAML while disabling all MQTT publishers at runtime.

The Supervisor endpoint documentation marks `GET /services/mqtt` as protected,
documents the bearer token from `SUPERVISOR_TOKEN`, and lists the returned
service fields: [Supervisor API endpoints](https://developers.home-assistant.io/docs/api/supervisor/endpoints/).
The app configuration documentation lists `hassio_api` as the separate
Supervisor REST API permission: [App configuration](https://developers.home-assistant.io/docs/apps/configuration/).
The add-on manifest will request `services: [mqtt:want]` and no `hassio_api`;
confirm that this is sufficient on a real Home Assistant installation before
release (`PENDING-HIL`).

If Supervisor returns 400 or 404, the target becomes unhealthy with the reason
`supervisor mqtt service unavailable`, the condition is logged once without
credentials, and the reconnect loop retries with bounded backoff.

### Hot backup

`tonewatch db checkpoint` runs `PRAGMA wal_checkpoint(TRUNCATE)` against the
live `tonewatch.db`. It retries transient writer contention until a bounded
deadline and exits non-zero with a clear error if the writer never releases the
database. It never replaces, deletes, or rewrites the database file. M10b can
therefore use `backup_pre: tonewatch db checkpoint` with a hot backup so the
paging monitor remains running during scheduled backups.

### Audio input

Choose the device-mapping path (decision **b**). The add-on supports an input
when the manifest maps the host audio device through its `audio: true` and
device configuration, and the operator selects the exposed ALSA device. The
image does not add `libasound2-plugins`, generate an `asound.conf`, or claim a
PulseAudio PortAudio device. Real capture and the exact HA audio mapping are
`PENDING-HIL`.

## Security impact

Supervisor MQTT credentials are a sensitive in-memory asset. The source marker
is safe to persist, but resolved host credentials are never copied into any
configuration model, audit record, log message, API response, or discovery
payload. The fake Supervisor tests cover bearer authorization, field resolution,
rotation on reconnect, the unavailable-service path, and redaction.
