# Brief: M19a-fix — admin health and delivery log: write the mandatory tests, pass the coverage gate, finish the gates

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a2bd-e3ef-70a0-b50c-6b14c1ada888`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19a`. **E2E port:** `TONEWATCH_E2E_PORT=8808` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, add `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** never write git state.

## Verdict on M19a: FAIL (no tests at all)
**PM verified what exists:**
- `admin/health.py` (195 lines), `api/routes/admin.py` (229 lines): `GET /api/admin/health` (`authenticated`), `GET /api/admin/alert-attempts`, `POST /api/admin/alert-attempts/{id}/retry` (`write_auth` + audit).
- Migration `0006_alert_attempt_retry` (boolean, server default 0).
- Repository functions; dispatcher, channel, supervisor and events hooks (+147 lines).
- Docs and threat model.
- `test_s4_security.py` has no diff.

**Why it fails:**
- The pytest count is **531 before and 531 after**, so **zero** of the mandatory tests A–K were written.
- `just check` fails the coverage gate (`api/routes/admin.py` 55 %, alerts 89 % against 90 %).
- `just e2e` and `ci-local` weren't run.

The brief said tests come first. Now write them against the existing code, and fix any bug they expose.

## Required
1. **Write every mandatory test A–K from `docs/pm/briefs/M19a-admin-health.md`** (read that file; it's the spec). Each must exist and assert the stated behaviour exactly. Summary:
   - **A.** Realtime factor EWMA with an injected clock (1 s of audio in 0.1 s gives ~10×; a slowdown shows up within the window).
   - **B.** Dropped and late frame counting through `Channel` with a fake source and engine.
   - **C.** Feed health history ring: bounded at 50, keeps order, has timestamps.
   - **D.** EventBus subscriber depth, dropped count and lag with a stalled subscriber.
   - **E.** Storage forecast:
     - the exact days value for a known rate
     - a zero rate gives `null`
     - zero free space gives 0
     - the disk scan runs in a thread and is cached for 60 s (a second call doesn't rescan), with `shutil.disk_usage` monkeypatched
   - **F.** Output stats: success → 3 failures → success gives exact `consecutive_failures` and timestamps. The error string is bounded and secret-free (a webhook URL with credentials, an MQTT password).
   - **G.** `GET /api/admin/health` via ASGI:
     - 401 without auth
     - an exact key-set snapshot of every section
     - `null`s without a supervisor
     - no injected secret anywhere in the body
   - **H.** Delivery log via ASGI with a real temp SQLite DB:
     - each filter (`call_id`, `target_id`, `phase`, `ok`, `since`, `until`)
     - cursor pagination with no duplicates or gaps across pages
     - `limit` > 200 gives 422; 401 without auth
   - **I.** Retry via ASGI with a real DB and a fake sender:
     - a failed webhook attempt gives exactly one send, one new row with `retry=true`, one `alert_attempt_retried` audit row, and `{ok:true}`
     - succeeded gives 409; missing call gives 409; target gone gives 409; unknown gives 404
     - concurrent gives 429
     - a cookie session without CSRF gives 403; no auth gives 401
     - a slow sender times out at the target's own timeout
     - a Meshtastic limiter drop gives `{ok:false, error:"rate_limited"}` plus a row
   - **J.** Migration 0006 upgrade → downgrade → upgrade on a real SQLite file keeps rows; the `retry` default is false for existing rows.
   - **K.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.
2. **Coverage:** `just check` must pass all existing coverage gates. Add tests rather than lowering any gate or adding exclusions.
3. **Scope check on your hooks:** add one regression test per touched hot path, all through existing public behaviour:
   - `dispatcher.py`, `channel.py`, `supervisor.py`: detection timing unchanged with health collection on, and alert delivery unchanged for a normal call (existing dispatcher tests still green, plus one asserting the stats update doesn't add sends).
4. **Gates:** `just check`, then `just e2e` (port 8808; if the launcher hangs after 4 specs pass, paste that line and continue), then `just ci-local` up to api-drift. Regenerate with `just gen-api` if needed.

## Evidence (the report is rejected without this)
- A table: test name → letter (A–K) plus item 3.
- For each test, the first-run result. If it passed immediately, say so. If it failed, show the failing line, the fix diff with file:line, and the passing line.
- The pytest count: 531 before, N after.
- The coverage lines for `api/routes/admin.py`, `admin/health.py` and alerts.
- `just check`, `just e2e`, `just ci-local` up to api-drift, and `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate or coverage threshold. No new `noqa`/`type: ignore`/`pragma: no cover` without a same-line justification.
- No new dependencies. Never write git state. Don't describe work you haven't done.
