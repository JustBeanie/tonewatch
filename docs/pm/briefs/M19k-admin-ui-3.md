# Brief: M19k — admin web UI for M19.4 drill, M19.5 config history and M19.7 logs/support bundle

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19k` (branch `m19k`). **E2E port:** `TONEWATCH_E2E_PORT=8852` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro, M19.4, M19.5 and M19.7.
- **The backend that exists** (read the route files for exact shapes; don't guess):
  - `api/routes/admin.py`:
    - `POST /api/admin/drill` → 202 `{drill_id, expected_duration_s}`, with 404/409/429 and ingress 403
    - the config history routes: `GET /config/versions`, `GET /config/versions/{id}`, `GET .../{id}/diff?against=`, `POST .../{id}/rollback` (If-Match required: missing gives 428, stale 412)
    - `GET /config/export` (masked) and `POST /config/export` (`{format, include_secrets, confirm:"include-secrets"}`, refused through ingress, with a `Warning` header)
    - `POST /config/import/preview` and `/apply` (a YAML/JSON body, If-Match on apply, 413 over the cap)
  - `api/routes/support.py`: `GET /api/admin/logs?level=&since_seq=&limit=` and `POST /api/admin/support-bundle` (a zip; 429 inside 30 s).
- The existing admin pages in `web/src/features/admin/` (Health, AdminAlerts, Deliveries, Credentials, Maintenance, Audit, `shared.ts`), the per-path diff rendering in `Audit.tsx` (**reuse it; don't write a second one**), `Shell.tsx`/`router.tsx`, and the readable-422 helper.

## Required (web only; no backend changes)
1. **Drill page** (`/admin/drill`):
   - a source picker (running sources only, from health or sources), a tone-set picker, mode (mix/replace, with a one-line explanation of each), voice seconds (0–20) and "keep this call"
   - a confirmation dialog stating plainly that **this sends real alerts to every configured target, marked DRILL**
   - after the 202, show the expected duration and a link to the calls list; watch for the drill's call via the existing WebSocket events (`useWsEvents`)
   - readable messages for 404/409/429 and the ingress 403
2. **Config history page** (`/admin/config`):
   - a version list (time, actor, route, short hash)
   - selecting a version shows its diff against current (reusing the Audit diff view)
   - "Roll back to this version" asks for confirmation, sends `If-Match` from the current `/api/config` ETag, and shows 412 as "changed elsewhere, reload" and 428 as a bug-level error
   - **Export:** a masked download (GET). "Include secrets" is a separate button with an explicit typed confirmation (the user types `include-secrets`), sends the POST and shows the plaintext warning; hide it through ingress
   - **Import:** a file input or paste area, "Preview" shows the diff or readable 422 errors, and "Apply" is enabled only after a successful preview of the **same** content and sends `If-Match`
3. **Logs and support page** (`/admin/logs`):
   - a live tail that polls every 3 s with `since_seq` while visible and pauses when `document.hidden`
   - a level filter and a pause button
   - bounded client-side (keep the last 2000 rows)
   - rows rendered as text (never HTML)
   - a "Download support bundle" button with a short note on what it contains and what it excludes; show the 429 readably
4. Add all three pages to the Admin nav group.

## Mandatory tests (write first; show each failing line)
- **A. Drill:** the confirmation text mentions real alerts and DRILL; the POST body is exact; 404, 409, 429 and 403 each show their message; the call link appears after the 202.
- **B. Config history:**
  - rollback sends `If-Match` equal to the current ETag
  - 412 and 428 render their messages
  - the diff renders masked values as text
  - the secret export requires the typed confirmation and is hidden through ingress
  - import apply is disabled until a preview succeeds, and editing the content after a preview disables it again
- **C. Logs:**
  - polling uses `since_seq` of the last row
  - it pauses when `document.hidden` (fake timers)
  - the 2000-row cap holds
  - a `<script>` in a log event renders as text
  - the bundle button posts and handles 429
- **D. Playwright** (extend `web/e2e/tonewatch.spec.ts`):
  - open Config history and see at least the startup baseline version
  - open Logs and see at least one row
  - open Drill and cancel the confirmation, making **no** POST; don't run a real drill in e2e
  - no external requests
- **E.** `git diff origin/main -- backend/` is empty (web only).

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` (Vitest count; web branch coverage **≥ 81 %**). Also run `just e2e` on port 8852 if your sandbox has browsers; **if it doesn't, say so**, and the PM runs it on the host. Then `just ci-local` through `api-drift`. `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result. Don't report `just check` as green unless you ran it in full after your last edit.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark the UI parts of M19.4, M19.5 and M19.7 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real incident data.
- **Parallel engineers:** M19i is in backup code and the CLI; M19l is in replay backend code. Stay in `web/**`.
