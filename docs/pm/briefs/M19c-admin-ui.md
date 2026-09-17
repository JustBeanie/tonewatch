# Brief: M19c — admin web UI for M19.1–M19.3 (System health, Admin alerts settings, Delivery log with retry)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19c` (branch `m19c`). **E2E port:** `TONEWATCH_E2E_PORT=8836` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 (~line 650): M19.1, M19.2, M19.3, and the rule that every mutating action uses auth + CSRF + audit and secrets are never shown.
- **The backend that exists** (read `api/routes/admin.py` for exact shapes):
  - `GET /api/admin/health` (the `HealthResponse` model, including `cad_feeds`)
  - `GET /api/admin/alert-attempts` (filters `call_id`, `target_id`, `phase`, `ok`, `since`, `until`, cursor pagination, `limit` ≤ 200)
  - `POST /api/admin/alert-attempts/{id}/retry`: 409 for succeeded, missing call or target gone; 404 unknown; 429 concurrent; `{ok:false, error:"rate_limited"}` for a Meshtastic limiter drop
  - admin alerts config lives in `AppConfig.admin_alerts` (`AdminAlertsConfig` in `config/models.py`), edited via `GET`/`PUT /api/config` with `If-Match`
- **Web patterns:** `web/src/features/cad/` and `agencies/` (component, hook and test splitting), `web/src/lib/ws.ts` (`useWsEvents` for discrete events), and the shared readable-422 error helper.
- **Config round-trip:** since `1fd0965`, `GET /api/config` masks only real secrets and a GET-then-PUT round-trip works. Still, **never send `"[REDACTED]"` for a field the user didn't edit**: send the body as received, and the server restores secrets. Test that a PUT of admin alerts leaves alert-target secrets intact.

## Required
1. **System health page** (`/admin/health`, a nav entry under an "Admin" group):
   - **Sources:** per source, the realtime factor (a warning below 1.5×), dropped or late frames, restarts, last error, squelch state and a feed health history sparkline or table. No new chart dependency: use simple inline SVG or a table.
   - **Event bus:** subscriber depth, dropped count and lag.
   - **Storage:** used and free space, the "full in N days" forecast (or "no growth"), and DB size.
   - **Outputs:** last success, last error and consecutive failures per target, plus MQTT state.
   - **CAD feeds:** connected, availability, last message, invalid count, active incidents.
   - **Build:** version, build and uptime.
   - Refresh every 10 s while visible; pause when `document.hidden`.
   - Nulls render as "—", never "null" or NaN.
2. **Admin alerts settings** (`/admin/alerts`): an enable toggle, target picker (multi-select of existing alert targets) and each threshold with its bounds from the model (the server 422 shown readably).
   - Save via `PUT /api/config` with `If-Match`. A 412 conflict shows "changed elsewhere, reload".
   - A short explanation that admin alerts are separate from pages and marked `admin`.
3. **Delivery log** (`/admin/deliveries`):
   - A table with time, call (a link), target, phase, outcome, status or error and a retry marker.
   - Filters mapped to query params (preserved in the URL); cursor "Load more" with no duplicates.
   - A **Retry** button only on failed attempts. It asks for confirmation, then shows the result inline:
     - ok
     - "already succeeded" (409)
     - "call or target no longer exists" (409)
     - "a retry is already running" (429)
     - "rate limited"
   - The list refreshes after a retry.
   - Error strings from the server are shown as text. Never render HTML from them.

## Mandatory tests (write first; show each failing line)
- **A. Health page (Vitest):**
  - renders every section from a fixture
  - null fields show "—"
  - a realtime factor of 1.2 shows the warning
  - polling pauses when `document.hidden` (fake timers)
- **B. Admin alerts form:**
  - bounds errors from the server 422 are readable
  - save sends `If-Match` and the full config body
  - 412 shows the conflict message
  - a body round-trip test proves no `"[REDACTED]"` is introduced for secrets the user didn't touch
- **C. Delivery log:**
  - filters serialize to query params and URL
  - "Load more" appends with no duplicates
  - Retry is visible only on failed rows
  - each of the result paths above renders its message
  - an error string containing `<b>` renders as text
- **D. Backend, only if you must change an endpoint** (avoid it): ASGI tests.
- **E. Playwright** (extend `web/e2e/tonewatch.spec.ts`):
  - open System health and see a source row for the e2e fixture source
  - open Admin alerts, enable with a target, save and reload (persisted)
  - open Delivery log and see at least one attempt row, if the fixture config produces one; otherwise the empty state
  - no external requests
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its failing and passing lines.
- `just check` (pytest and Vitest counts; web coverage ≥ 80 %), **`just e2e` on port 8836 with per-test lines for all specs**, and **`just ci-local` through `api-drift`**. If `api-drift` fails only because generated files are uncommitted, run `just gen-api` and confirm `git diff --stat -- web/src/api` is empty afterwards.
- `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark `docs/PROGRESS.md` M19.1–M19.3 UI notes `[~] ... — PENDING-REVIEW`; the backend parts are already ticked.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real incident data.
