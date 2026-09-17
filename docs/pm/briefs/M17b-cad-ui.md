# Brief: M17b — M17.5 CAD web UI (incident card, dashboard panel, agency/map incidents, feeds and unmatched pages)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m17b` (branch `m17b`). **E2E port:** `TONEWATCH_E2E_PORT=8832` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M17.5 (~line 604) and `docs/guide/cad.md`.
- **The backend that exists** (landed in `b4bc79d`): read `api/routes/cad.py`, `api/routes/calls.py` and `api/routes/config.py` for the exact shapes.
  - `/api/cad-feeds` CRUD, with secrets masked
  - `GET /api/cad/unmatched-agencies` and `POST /api/cad/unmatched-agencies/{key}/create-agency`
  - `GET /api/calls/{id}` returns `cad_incidents: [...]`, and `GET /api/calls` returns `has_cad`
  - `GET /api/admin/health` has a `cad_feeds` section
  - the WebSocket `CallEnriched` event (`api/ws_models.py`)
- **Web patterns** (landed in `ef88068`):
  - `web/src/features/agencies/`, `web/src/features/map/`, `web/src/features/alerts/` (component, hook and test splitting)
  - **`web/src/lib/ws.ts` `useWsEvents`**: discrete events **must** use this lossless per-message hook, not `useSubscription`
  - the readable FastAPI 422 error helper used in `AgencyForm.tsx` (reuse it; move it to `web/src/lib/` if it isn't shared yet)

## Required (M17.5)
1. **Call detail incident card.** When `cad_incidents` is non-empty, show:
   - type (raw, and code if present)
   - address (`address_clean`) and cross streets
   - municipality
   - received time (local, plus the delta to the call start)
   - the feed name

   It updates live on `CallEnriched` for the open call, with no reload.
2. **Calls list:** a small CAD badge when `has_cad`, and it updates live on `CallEnriched`.
3. **Dashboard CAD panel:** active incidents for **configured agencies only** (incidents whose agency matches any `Agency.cad_names`), newest first, capped at 10, each linking to its call if linked.
   - Hidden when no CAD feeds are configured.
   - **If no endpoint lists active incidents, add a minimal backend one**, e.g. `GET /api/cad/incidents?status=active&configured_only=true&limit=`. Use `authenticated`, validated params, and an ASGI test. It must return only the fields the UI needs, and **never log incident fields**.
4. **Agency card (Map page) and agency detail:** show recent incidents for that agency (last 5). Incidents have no coordinates, so they're listed under the agency, not plotted.
5. **Settings: CAD feeds page** (`/settings/cad-feeds`, or a section matching existing settings navigation), with list, add, edit and delete for `cad_feeds`.
   - Fields: MQTT target reference **or** host, port, tls, username, password (exactly one, mirroring the model validator); base topic; window before and after in seconds; enabled.
   - Passwords are write-only: empty on edit means keep. **Never send `[REDACTED]` back**; omit the key instead.
   - Show per-feed health (connected, availability, last message, invalid count, active incidents) from admin health.
6. **Unmatched CAD agencies page** (nav, near Discovered tones): name, count, last seen, and "Create agency", which calls the create endpoint then navigates to the new agency's editor.
7. **Privacy:** addresses appear only on authenticated pages (all app pages are). Don't put addresses in the document title, URLs, `console` logs or error toasts.

## Mandatory tests (write first; show each failing line)
- **A. Vitest, incident card:** renders all fields from a fixture; a same-tick `CallEnriched` plus another event both apply (lossless hook); no card when empty.
- **B. Vitest, calls badge:** `has_cad` shows the badge, and a live `CallEnriched` adds it.
- **C. Vitest, dashboard panel:** hidden with no feeds; shows a maximum of 10 configured-agency incidents newest first; links to calls.
- **D. Vitest, CAD feed form:**
  - the exactly-one-of broker rule enforced in the UI
  - the server 422 shown readably
  - an edit with an empty password omits `password` from the PUT body, and **never** sends `"[REDACTED]"`
- **E. Vitest, unmatched agencies:** create calls the endpoint and navigates.
- **F. Backend** (only if you add the incidents endpoint): ASGI filters, auth 401, limit validation 422, and a `caplog` check with no incident fields.
- **G. Playwright** (extend `web/e2e/tonewatch.spec.ts`; no real MQTT broker):
  - create a CAD feed through the UI (it may stay disconnected)
  - assert it's listed with disconnected health
  - open the unmatched agencies page (the empty state is fine)
  - no external requests (`page.on("request")`)
- **H.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its failing and passing lines.
- `just check` (pytest count, Vitest count, web coverage ≥ 80 %), then `just e2e` on port 8832 with **per-test lines for every spec**, then `just ci-local` up to `api-drift`. `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark `docs/PROGRESS.md` M17.5 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate.
- **A parallel engineer is changing `backend/src/tonewatch/api/audit.py`, `api/deps.py` and `logging.py` (secret masking).** Don't touch those files.
- No real incident data in fixtures: invented agencies and addresses only.
