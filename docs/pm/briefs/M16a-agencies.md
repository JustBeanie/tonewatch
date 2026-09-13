# Brief: M16a — agencies data model, API and map settings (backend: M16.1–M16.3)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16a` (branch `m16a`, based on `origin/main`). **E2E port:** `TONEWATCH_E2E_PORT=8805`.

## Goal
Implement `PLAN.md` M16.1–M16.3: rich per-agency data linked to tone sets, carried on calls and events, and served as GeoJSON for a future map. **The web UI (M16.4) and Home Assistant parts (M16.5) are out of scope,** except that event payloads must carry the agency. Two other engineers are working in parallel on M14a (live restream) and M15a (squelch). Keep edits to shared files (`config/models.py` `AppConfig`, the generated web client, `docs/PROGRESS.md`) small and additive. You own migration `0005`; nobody else adds a migration in this wave.

## Required
1. **Models (`config/models.py`, test-first).** Implement `Agency` exactly as in PLAN M16.1, as frozen pydantic models:
   - `Slug` id; `kind` enum; `color` validated `#RRGGBB`.
   - `location` and station coordinates: lat in [-90, 90] and lon in [-180, 180], both finite.
   - `website` limited to http/https.
   - `notes` at most 4,000 chars; every other string bounded (pick limits and list them in the report).
   - **`coverage`:** GeoJSON `Polygon` or `MultiPolygon` only. Validate RFC 7946 structure with your own small validator (don't add a GIS dependency):
     - positions are `[lon, lat]` in range
     - linear rings have at least 4 positions and are closed
     - at most 10,000 vertices in total and 256 KB serialized
   - `cad_names: list[str]`: at most 20 names, each 1–120 chars. Trim them and make them unique case-insensitively. For now only store and validate them. A later milestone (M17) matches them against CAD incident feeds, so also expose them in the API and in the GeoJSON `properties`.
   - `AppConfig.agencies` (at most 500) with unique ids.
   - `ToneSet.agency_id: Slug | None = None`, reference-checked in `AppConfig`'s validator like alert targets.
   - **Deleting an agency still referenced by tone sets** is rejected with a clear error that lists those tone-set ids (in the store/API layer, returning 409).
2. **API (`api/routes/agencies.py`).**
   - CRUD `/api/agencies` mirroring the tone-set routes exactly: auth, CSRF, hot-apply to YAML through the config store, and audit events (`agency_created`, `agency_updated`, `agency_deleted`).
   - `GET /api/agencies.geojson` returns a `FeatureCollection`:
     - one Point feature per agency location
     - one Point per station, with `properties.station_of`
     - one feature per coverage
     - properties: `id`, `name`, `short_name`, `kind`, `color`
     - `Content-Type: application/geo+json`
   - Tone-set create/update accepts `agency_id`, with a 422 for an unknown agency.
   - Regenerate the web client (`just gen-api`).
3. **Calls and events.**
   - Alembic migration `0005_call_agency_snapshot` adds nullable `agency_id`, `agency_name` and `agency_kind` to `CallToneSet`. Upgrade and downgrade are both tested.
   - When a call is persisted, snapshot the linked agency of each matched tone set. Call list and detail responses include it.
   - Add a calls-list filter `agency_id`.
   - Rename or delete the agency afterwards, and the call still shows the snapshot. Test this.
   - The detection event payloads (WS event, MQTT call topic, webhook JSON, and anything the HA discovery `event` entity publishes) gain `agency: {id, name, short_name, kind, lat, lon} | null`. Update their payload tests. This is additive; don't rename existing fields.
4. **Map settings and CSP (M16.3).**
   - Add `AppConfig.map: MapConfig` with `tile_url: str = ""` and `attribution: str = ""`. When `tile_url` is set, it must be an `https` URL template containing `{z}`, `{x}` and `{y}`, with no credentials, query-string secrets or non-default ports. Also add a constant OpenStreetMap preset (`https://tile.openstreetmap.org/{z}/{x}/{y}.png` with its required attribution text) that the API exposes, e.g. in a settings or map-config response, for the future UI one-click preset.
   - The SPA CSP (`api/spa.py`) keeps `img-src 'self'` when `tile_url` is empty. When it is set, add **only that exact scheme+host origin** to `img-src`, and nothing else anywhere. The CSP must follow hot-applied config.
   - Tests prove: no external origin with an empty `tile_url`; the exact origin appears once when set; injection attempts (`;`, spaces, quotes, `*`, `data:`) are rejected at validation.
5. **Security docs.** Add threat-model entries for the map tile origin (viewer IP and area leaked to the tile provider; off by default) and for GeoJSON input size and complexity DoS. Add ASVS checklist rows for the new routes, following the existing file conventions exactly (quoting, LF, line anchors).
6. **Public docs.** Add an "Agencies" docs page: the fields, linking tone sets, GeoJSON coverage format with a tiny example, and the map tile privacy note.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate: no skips, no lowered coverage, no CSP widening beyond the configured tile origin, no `# type: ignore`/`noqa` without a same-line justification.
- Never print, log or commit anything from `backend/tests/fixtures/private/`. Don't derive agencies from the private `tones.cfg` fixture.
- Use only invented agency names and coordinates in tests and docs; no real departments.
- No legacy product naming (the clean-room pre-commit hook enforces it).
- Never commit or push. Don't bump unrelated pins or add dependencies; if one seems necessary, stop and explain it in the report.

## Definition of done
- `just check` passes. Paste the pytest and vitest summary lines.
- `just ci-local` with `TONEWATCH_E2E_PORT=8805` passes, including security, api-drift and e2e. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- In `docs/PROGRESS.md`, M16.1–M16.3 are marked `[~] PENDING-REVIEW`, one line each.
- The final report lists every changed file, all field limits, the GeoJSON validator rules, the exact event payload diff, and the CSP tests.
