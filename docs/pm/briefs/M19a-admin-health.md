# Brief: M19a — admin health API and alert delivery log with retry (PLAN M19.1 + M19.3, backend only)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19a` (branch `m19a`, from `origin/main`, which already has M14a/M15a/M15b/M16a/M18a). **E2E port:** `TONEWATCH_E2E_PORT=8808` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, add `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** your sandbox can't write git state in this worktree. Never run fetch, stash, merge, add or commit. Read-only diff/status/show is fine.

## Read first
- `PLAN.md` M19 intro, M19.1 and M19.3 (the spec). Every mutating action uses auth + CSRF + an audit event; secrets are never shown or logged.
- **Existing hooks to build on:**
  - `events.py` `EventBus` subscriptions (`dropped`, queue)
  - `sources/soundcard.py` `dropped`
  - `pipeline/watchdog.py` + `FeedHealthChanged`
  - `pipeline/channel.py` (squelch state, `live_hub`)
  - `pipeline/supervisor.py` (channel restarts)
  - `alerts/dispatcher.py` (`_dispatch`, `_send`, `_record`, `test_target`)
  - `storage/models.py` `AlertAttempt`
  - `recording/retention.py`
  - `api/routes/system.py` (`/healthz`, `/readyz`)
  - `api/routes/audit.py`
  - `api/deps.py` (`write_auth`, `_dump`/`mask_secrets`)

## Scope
- **In:** M19.1 backend and M19.3 backend.
- **Out:**
  - UI pages (a later brief)
  - M19.2 admin alerts (a later brief, M19b, which will consume what you build here, so keep the health model reusable)

## Required
1. **Metrics collection (pure, test-first).** A small `tonewatch/admin/health.py` (or similar) with no new dependencies.
   - **Per channel:**
     - **Realtime factor:** audio seconds processed ÷ wall seconds spent in DSP, as an exponentially-weighted moving average (EWMA) over about the last 30 s. Take it from existing per-frame processing with an injectable clock, so it's testable without real time.
     - **Dropped or late frames** (soundcard `dropped`, plus frames whose processing exceeded their duration).
     - **Restarts** (count + last restart time from the supervisor).
     - **Last error** (bounded string, never audio or secrets).
     - **Feed health history:** a bounded ring of the last 50 `FeedHealthChanged` transitions with timestamps.
     - **Level and squelch state:** reuse the existing status fields.
   - **Service:** per EventBus subscriber queue depth, `dropped` count, and lag (the age of the oldest queued event).
   - **Storage:**
     - recordings directory size and filesystem free space (`shutil.disk_usage`)
     - DB file size (plus WAL)
     - a **retention forecast** from the write rate over a sliding window, using completed recordings' sizes and times: `days_until_full = free_bytes / bytes_per_day`, or `null` when the rate is 0 or unknown. Bound it at 10 years and never divide by zero.
   - **Outputs:**
     - per alert target: `last_success_at`, `last_error_at`, `last_error` (bounded, secret-free), `consecutive_failures`, all updated from dispatcher attempt outcomes
     - MQTT connection state for MQTT and Meshtastic senders, if they already expose it; otherwise `null` with a TODO in the report
   - **Build:** version (existing `__version__`), build info if available, process uptime.
2. **`GET /api/admin/health`:** authenticated (read), returning one JSON document with sections `sources`, `service`, `storage`, `outputs`, `build`, plus `generated_at`.
   - Every field is present with `null` when unknown; never omit keys. Document the schema in the OpenAPI response model (pydantic).
   - No secrets anywhere: target entries carry id, name, type and the stats above, never URLs with credentials, passwords or tokens.
   - Computing it must not block the event loop. Do disk scans in a thread with a cached result, refreshed at most every 60 s.
3. **Delivery log:** `GET /api/admin/alert-attempts` (authenticated).
   - Filters: `call_id`, `target_id`, `phase`, `ok` (bool), `since`, `until`.
   - Cursor pagination (`limit` ≤ 200, default 50, a stable order by `created_at desc, id desc`), with total count omitted for performance.
   - The response rows carry `id, call_id, target_id, phase, attempt_no, ok, status_code, error (bounded), created_at, retry (bool)`.
   - Add the needed repository functions in `storage/repository.py`.
4. **Retry:** `POST /api/admin/alert-attempts/{id}/retry`, with `write_auth` + CSRF.
   - Only for a **failed** attempt whose call exists and whose target still exists in the current config. Otherwise: 404 (unknown attempt), 409 (attempt succeeded, call missing, or target gone), 429 (a retry for the same attempt already in flight).
   - Performs **exactly one** send through the dispatcher's normal sender for that target type. Rebuild the payload from the stored call and the current config, with `retry: true` in the payload.
   - Records **one** new `AlertAttempt` row marked `retry=true`: add a migration `0006` with a boolean column, default false, and test upgrade and downgrade.
   - Writes an audit event `alert_attempt_retried` (attempt id, target id, ok; no secrets).
   - Bound it by the target's own timeout. Return `{ok, error}`.
   - Meshtastic targets obey their rate limiter. A limiter drop returns `{ok:false, error:"rate_limited"}` and records that row.
5. **Docs:** a short admin section in the guide (health fields, forecast method, retry rules); PROGRESS notes on M19.1/M19.3 marked PENDING-REVIEW (backend); threat model + ASVS rows for the new endpoints, following the existing conventions (quote-all CSV, LF, re-derived anchors); and `just gen-api`.

## Mandatory tests (the report maps test name to letter)
- **A.** Realtime factor EWMA with an injected clock: 1 s of audio processed in 0.1 s gives ~10×, and a slowdown is reflected within the window.
- **B.** Dropped and late frame counting through `Channel` with a fake source and engine.
- **C.** Feed health history ring is bounded at 50, keeps order, and has timestamps.
- **D.** EventBus subscriber depth, dropped count and lag with a stalled subscriber.
- **E.** Storage forecast:
  - a known write rate gives the exact days value
  - a zero rate gives `null`
  - free space 0 gives 0
  - `shutil.disk_usage` is monkeypatched, and the disk scan runs in a thread and is cached (the second call within 60 s doesn't rescan)
- **F.** Output stats: success, then 3 failures, then success, giving the exact `consecutive_failures` sequence and timestamps. The error string is bounded and contains no secret (use a webhook URL with credentials, and an MQTT password).
- **G.** `GET /api/admin/health` via ASGI:
  - 401 without auth
  - every documented key present (a schema snapshot test on key sets), with `null`s when no supervisor
  - no secret values anywhere in the body (search for the injected secrets)
- **H.** Delivery log via ASGI with a real temp SQLite DB: each filter, pagination with a cursor (no duplicates or gaps across pages), `limit` > 200 gives 422, and 401.
- **I.** Retry via ASGI with a real DB and a fake sender:
  - a failed webhook attempt gives one send, one new row with `retry=true`, the audit row, and `{ok:true}`
  - a succeeded attempt gives 409; a missing target gives 409; unknown gives 404
  - concurrent retry gives 429
  - no CSRF on a cookie session gives 403; no auth gives 401
  - a timeout at the target's timeout surfaces an error
  - a Meshtastic limiter drop gives `rate_limited` and a row
- **J.** Migration 0006 upgrade, downgrade and upgrade on a real SQLite file keeps rows.
- **K.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Evidence (the report is rejected without this)
- The test-name → letter table.
- For each required item 1–4, the first failing test line (test-first), the passing line, and a diff excerpt with file:line.
- The pytest count on main at your base (run `just test` first and record it) and after.
- `just check`, `just e2e` (port 8808; if the launcher hangs after 4 specs pass, paste that line and continue), and `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting the result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification. No new dependencies.
- No real radio data or private fixtures.
- Never write git state. Don't describe work you haven't done.
