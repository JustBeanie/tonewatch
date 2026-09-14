# Brief: M16a-fix2 — agencies: the mandatory tests you skipped

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1ba-d1c6-7ce0-8b17-b72f382b9ee3`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16a`. **E2E port:** `TONEWATCH_E2E_PORT=8805` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M16a-fix: FAIL (tests)
**PM verified in code and kept:**
- `replace_config` is used at every rebuild site: deps, config routes, agencies, importer, add-on supervisor.
- `Channel.agency_lookup` is late-bound to `Supervisor.config`, and `reload` calls `alerts.reload`.
- The dispatcher builds `agency` from its current config.
- The brace check on the tile netloc and the `:443` stripping are in place.
- The `geojson` special case is gone.

**Why it fails:** your run added 7 tests (408 → 415). The M16a-fix brief listed about 20 mandatory tests, and the report gave no red-first line per fix and no test → requirement map. Code without the required tests does not pass.

## Required: add these tests (each is mandatory)
Put them in `backend/tests/unit/test_m16a.py` or `backend/tests/integration/test_m16a_api.py`.

1. **Agency-only reload, end to end.**
   - Build a real `Supervisor` with a file or fake source and a tone set linked to an agency.
   - Rename the agency through `Supervisor.reload(replace_config(...))`, then trigger a detection.
   - Assert all three:
     - The channel task object is the **same** before and after (no restart).
     - The `ToneDetected` on the bus carries the new name.
     - The dispatcher payload carries the new name.
2. **`replace_config` over every mutation path.**
   - Parametrize over `AppConfig.model_fields`, building a config where **every** field holds a non-default value. Include `discovery`, `map`, `agencies`, `live_stream` if present, retention/auth/mqtt sections, and every other field.
   - Mutation paths:
     - tone-set create, update, delete
     - source create, update, delete
     - alert-target CRUD
     - agency CRUD
     - tones.cfg apply
     - add-on MQTT target
   - For each path, assert every field it doesn't own is unchanged. Add a guard assertion that the set of fields you populated equals `AppConfig.model_fields`, so a new field fails the test until someone adds it.
3. **Tile URLs:** `https://tiles.example:8443/{z}/{x}/{y}.png` is rejected. The `:443` case asserts the **exact** full CSP header string.
4. **Missing agency reference:** creating a tone set whose `agency_id` names a missing agency returns 422 through the tone-set API, and the response names the id.
5. **Coverage validation:**
   - valid MultiPolygon, and invalid MultiPolygon (unclosed ring)
   - over 256 KB serialized is rejected
   - `bool` coordinates are rejected
   - NaN and inf are rejected
   - a Polygon with a hole ring is accepted
6. **Migration 0005 on a real SQLite file via Alembic:**
   - Upgrade to head: the new columns exist.
   - Insert a call row, then downgrade to 0004: the columns are gone and the row is kept.
   - Upgrade again.
7. **Call snapshot survives agency changes:**
   - Persist a call for a tone set linked to an agency.
   - Rename the agency, then unlink it and delete it.
   - Call list and detail still show the original `agency {id, name, kind}`, and `GET /api/calls?agency_id=<id>` still returns the call.
8. **Event payloads,** agency present **and** `null` when unlinked, asserting existing keys are unchanged:
   - the dispatcher payload `agency` has exactly `id, name, short_name, kind, lat, lon`
   - the MQTT call-topic JSON
   - the webhook JSON body
   - the HA discovery `event` entity payload
9. **CSP at app level** via the ASGI app:
   - An HTML route with empty `map.tile_url` has no `https://` origin.
   - Save a map config through the config API (the store + reload path); the next HTML response has exactly that origin once, in `img-src` only.
   - A JSON API response still has the deny-all CSP.
10. **GeoJSON shape:**
    - Point coordinates are `[lon, lat]`.
    - Station features carry `station_of`.
    - The coverage feature appears exactly once.
    - An agency with no stations or coverage yields exactly one feature.
11. **An agency with id `geojson`** is reachable via `GET /api/agencies/geojson` and returns that agency, not the collection.
12. **Docstring:** restore the original `_set_api_csp` docstring **verbatim**:
    `"""Deny all content for non-HTML API responses while forbidding foreign framing."""`

If any test exposes a bug, fix the code, and show the failing line before the fix.

## Evidence (the report is rejected without this)
- A table mapping each test name to its requirement number (1–12).
- For each item, the red-first or first-run line and the passing line. For tests that pass immediately against already-fixed code, say so explicitly and show the passing line.
- The pytest count before (415 collected) and after.
- `just check` and `just e2e` summary lines, then `just ci-local` up to api-drift, with `git diff --stat -- web/src/api`.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- Invented agency names and coordinates only; never private fixtures.
- Never `git add`, commit or push. Don't describe work you haven't done.
