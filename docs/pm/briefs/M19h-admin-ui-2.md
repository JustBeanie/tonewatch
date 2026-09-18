# Brief: M19h — admin web UI for M19.8 credentials, M19.9 maintenance and M19.11 audit log (plus the audit API filters)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19h` (branch `m19h`). **E2E port:** `TONEWATCH_E2E_PORT=8846` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro, M19.8, M19.9 and M19.11.
- **The backend that exists** (read the route files for exact shapes; don't guess):
  - `api/routes/credentials.py`: `POST /api/admin/credentials/api-token/rotate` `{grace_seconds}` → `{token, previous_valid_until}`, `live-secret/rotate`, `ui-password` `{current_password, new_password}`, `sessions/revoke-all`. Ingress gets 403 on all of them.
  - `api/routes/maintenance.py`: the retention preview/run, database checkpoint/vacuum and orphans preview/apply (`expected_counts`, `invalid_rows`), each with 409 when busy.
  - `api/routes/audit.py`: `GET /api/audit`, currently only `limit` plus an **offset** cursor.
- The existing admin pages in `web/src/features/admin/` (Health, AdminAlerts, Deliveries, `shared.ts` formatters), `web/src/app/Shell.tsx` (the Admin nav group) and `router.tsx`, and the shared readable-422 error helper.

## Required
### Backend (only this change)
1. **Audit API filters and a stable cursor** in `api/routes/audit.py`:
   - filters `actor`, `event_type`, `resource` (exact match), `since` and `until` (ISO datetimes, 422 if malformed or reversed)
   - replace the offset cursor with a keyset cursor (`before_id`), so new events arriving between pages never cause duplicates or gaps
   - `limit` stays ≤ 200
   - Keep the response shape; `next_cursor` becomes the id to pass as `before_id`. **ASGI tests first:** each filter, the reversed range 422, and the no-duplicate test (insert rows between page 1 and page 2).

### Web
2. **Credentials page** (`/admin/credentials`):
   - **Rotate API token:** a grace selector (0, 5 min, 1 h default, 24 h) and a confirmation dialog. It shows the new token **once**, in a copy field with a clear "this is the only time it's shown" warning, plus the old token's expiry.
     - Leaving or reloading the page drops the token (component state only; **never** localStorage, the query cache or the URL).
     - If the page itself authenticates with the bearer token, explain that the old one stops working at the expiry.
   - **Rotate live secret:** a confirmation dialog explaining that all live links stop and listeners disconnect.
   - **Change UI password:**
     - current, new and confirm fields, where new must be at least 12 characters and match confirm (checked client-side and shown from the server 422)
     - 403 shows "current password is incorrect"
     - 429 shows "too many attempts, wait"
     - password fields are `autocomplete="current-password"` / `"new-password"` and are cleared after submit, success or failure
   - **Revoke all sessions:** a confirmation dialog explaining that this signs everyone out, **including you**. After success, go to the login flow.
   - Under ingress (the 403 "credential changes require…"), show one readable notice instead of the buttons failing one by one. Detect it from `/api/auth/status` `via === "ingress"`.
3. **Maintenance page** (`/admin/maintenance`):
   - **Retention:** a "Preview" button showing the counts (files and bytes via `formatBytes`, calls, CAD incidents, discovered). "Run now" is enabled only after a preview and asks for confirmation restating those counts.
   - **Database:** checkpoint and vacuum buttons showing before/after sizes. Vacuum asks for confirmation.
   - **Orphans:** a preview lists files (relative path and size) and rows with missing files, with counts, and shows `invalid_rows` as a warning.
     - Apply has "delete files" and "delete rows" checkboxes and sends the previewed `expected_counts`.
     - A 409 "counts changed" shows "changed since preview, preview again" and disables apply until a new preview.
   - Any 409 "maintenance operation already running" shows readably.
   - Show one action at a time: disable the other buttons while a request is in flight.
4. **Audit log page** (`/admin/audit`):
   - a table with time, actor, event type and resource
   - filters mapped to URL query params
   - "Load more" through `before_id`
   - a row expands to show `details`, and **for config changes a before/after diff view** (per changed path; values rendered as text, masked values stay masked)
   - Never render HTML from any field.
5. Add the three pages to the Admin nav group.

## Mandatory tests (write first; show each failing line)
- **A. Backend audit:** the ASGI tests from item 1.
- **B. Credentials (Vitest):**
  - the token is shown once and is gone after unmount/remount
  - it's never written to `localStorage`/`sessionStorage` (spy on both)
  - it's never in the TanStack Query cache (inspect `queryClient.getQueryCache()`)
  - the password fields clear after both a 403 and a success
  - 422, 403 and 429 show their messages
  - ingress mode shows the notice and no action buttons
  - revoke-all redirects to login
- **C. Maintenance:**
  - run-now is disabled before a preview, and its confirmation restates the counts
  - orphan apply sends exactly the previewed `expected_counts`
  - a 409 "counts changed" forces a new preview
  - the busy 409 message renders
  - invalid rows show a warning
- **D. Audit page:**
  - filters serialize to URL params and back
  - Load more appends with no duplicates
  - a config change row renders its diff
  - a `<b>` in any field renders as text
- **E. Playwright** (extend `web/e2e/tonewatch.spec.ts`):
  - open Maintenance, run retention preview and see counts
  - open Audit log and see at least one row (e.g. created by that preview)
  - open Credentials and rotate the live secret with confirmation
  - **do not** rotate the API token or revoke sessions in e2e (the spec depends on them)
  - no external requests
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` (pytest and Vitest counts; web branch coverage **≥ 81 %** for margin, with every backend package coverage line at least 1 % above its gate). Also run `just e2e` on port 8846 if your sandbox has browsers; **if it doesn't, say so**, and the PM runs it on the host. Then `just ci-local` through `api-drift` (run `just gen-api`). `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark the UI parts of M19.8, M19.9 and M19.11 `[~] ... — PENDING-REVIEW` in `docs/PROGRESS.md`.
- No new dependencies (no diff library: write a small path-diff for JSON objects). No subdirectory `conftest.py`. Never weaken a gate. No real incident data.
- **Parallel engineers:**
  - **M19f** is in `config/store.py`, `api/routes/config.py` and a new config-history route.
  - **M19g** is in `logging.py` and a new support/logs route.

  Backend-wise, you may only edit `api/routes/audit.py` and its tests.
