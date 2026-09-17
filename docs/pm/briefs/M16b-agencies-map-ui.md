# Brief: M16b — M16.4 agencies editor, Map page, live pulse, calls filter

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m16b` (branch `m16b`). **E2E port:** `TONEWATCH_E2E_PORT=8828` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M16 (~lines 540–567), especially M16.4 and "Done when".
- **Backend that already exists:**
  - `api/routes/agencies.py`: `GET/POST /api/agencies`, `GET/PUT/DELETE /api/agencies/{id}`, `GET /api/agencies.geojson`
  - `GET /api/map-config` (`map` policy plus `osm_preset`)
  - `api/spa.py` CSP, which allows only the configured tile origin in `img-src`
  - `config/models.py` `Agency`, `AgencyLocation`, `AgencyStation`, coverage validation
  - the call agency snapshot on calls
- **Web conventions:**
  - `web/src/features/*` (see `alerts/` after M18b for component, hook and test splitting)
  - `web/src/api/client.ts`
  - `web/tests/*.test.tsx`
  - `web/e2e/tonewatch.spec.ts`
  - `scripts/e2e_fixture.py` (the e2e config generator)

## Dependency (PM-authorized)
- Add **`leaflet`** (BSD-2-Clause) and **`@types/leaflet`** (dev) with pnpm, and commit the lockfile change.
- **No** `react-leaflet` and no other map or geo packages. Wrap Leaflet imperatively in a small component with a ref and cleanup.
- Import Leaflet's CSS from the package. **Default marker icons break under Vite** (image URLs), so use `L.divIcon` or `L.circleMarker` rather than the default PNG icons, and fetch no external assets.
- **No tiles unless configured:** if `map.tile_url` is empty, render the map with no tile layer (markers and coverage on a blank background) plus a notice that links to Settings. The CSP only permits the configured tile origin, so never hardcode OSM.
- The license check in `just security` must pass.

## Required (M16.4)
1. **Agencies page** (`/agencies`, nav entry):
   - **List:** name, kind, number of linked tone sets, has location or coverage.
   - **Editor:**
     - name, short name, kind
     - address fields
     - `cad_names` (a tag input)
     - location set by clicking the map, or typed lat/lon
     - stations added by map click, each with a name
     - coverage GeoJSON pasted or uploaded as a `.geojson` file (≤ the backend limit), validated server-side with 422 messages shown inline
     - linked tone sets
   - Delete asks for confirmation.
   - Use the existing ETag/`If-Match` concurrency if the agencies API supports it; otherwise follow the tone set editor pattern.
2. **Map page** (`/map`):
   - Markers for agency locations and stations, and coverage polygons coloured by agency kind, from `/api/agencies.geojson`.
   - Clicking opens an agency card with its name, kind, tone sets and last 5 calls (the calls API filtered by agency).
   - The tile layer comes from `/api/map-config`, with the attribution shown when set.
   - **Live pulse:** subscribe to the existing WebSocket event stream. On a call start whose agency snapshot matches, pulse that agency's marker until the call closes. Respect `prefers-reduced-motion` with a static highlight instead.
3. **Calls list filter by agency.** If the calls API lacks an `agency_id` filter, add it in the backend (query param, validated, tested) and regenerate the client.
4. **Accessibility:** every map interaction has a non-map equivalent (typed coordinates, the list view). Keyboard reachable. jsx-a11y clean.

## Mandatory tests (write first)
- **A. Vitest, editor:**
  - a map click sets lat/lon fields (mock the Leaflet map click through your wrapper's handler)
  - typed coordinates update the marker
  - a pasted invalid GeoJSON shows the server's 422 inline
  - `cad_names` tags serialize
- **B. Vitest, Map page:**
  - features from a mocked geojson render markers and polygons (assert on your wrapper's calls or DOM)
  - no tile layer and a notice when `tile_url` is empty
  - a WS call-start event for the agency adds the pulse class, and call close removes it
  - reduced motion uses the static class
- **C. Vitest:** the calls filter by agency calls the API with `agency_id`.
- **D. Backend (only if you add the filter):** ASGI test for `agency_id` filtering and 422 on a bad value.
- **E. Playwright** (extend `web/e2e/tonewatch.spec.ts`; update `scripts/e2e_fixture.py` if needed):
  - create an agency in the UI and place it with typed coordinates
  - link the e2e fixture tone set to it
  - trigger the fixture page
  - the call shows the agency, and the Map page shows its marker with the pulse class
  - no external network requests: assert `page.on("request")` saw no non-localhost URLs
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its first-run failing line and its passing line.
- `just check` (Vitest coverage must stay ≥ 80 %), `just e2e` on port 8828, then `just ci-local` up to `api-drift`. `git diff --stat`, including `web/pnpm-lock.yaml`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` code and pasting that result. Don't cite sources you didn't read.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark `docs/PROGRESS.md` M16.4 `[~] ... — PENDING-REVIEW`.
- Only the two authorized packages. Never weaken a gate. No `eslint-disable`/`ts-ignore` without a same-line justification.
- **Don't add conftest.py files in subdirectories.** Tests must not open real network sockets or fetch tiles.
- A parallel engineer is building M17 CAD backend in another worktree. Don't touch `cad/` or migrations, to avoid conflicts. If you need a backend change, keep it to the calls filter.
