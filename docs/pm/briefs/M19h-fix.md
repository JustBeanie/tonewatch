# Brief: M19h-fix — remove a test-double hack from production code, format the grace expiry, and pin the audit time filters

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b605-7a2f-7551-b0c7-ec18a7aff6a2`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19h` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8846`. `docs/pm/briefs/M19h-admin-ui-2.md` still applies.

## PM review
Good work: the PM reran host `just e2e` and all 14 specs passed. Three fixes are needed before merging. Write a failing test first for each, and paste its failing line as you go.

1. **Production code accommodates a test double.**
   - `api/routes/audit.py` computes `next_cursor` with `page[-1].id if isinstance(page[-1], AuditEvent) else limit`, "for lightweight session doubles that still model offset pages". If that branch ever ran, `limit` would be returned as an id, which is a wrong cursor.
   - **Fix:** always return `str(page[-1].id)`. Find the tests that use such a double (grep `backend/tests` for session doubles hitting `/api/audit`) and change **those tests** to a real temporary SQLite session, or to a double that yields real `AuditEvent` rows.
   - Report which tests you changed and confirm none of them is `test_s4_security.py`. If one is, **stop and report**; don't edit it.
2. **The grace expiry renders as a raw number.**
   - The backend returns `previous_valid_until` as epoch **seconds** (`int | null`), but `Credentials.tsx` types it as `string | null` and shows it as-is ("valid until 1790000000").
   - **Fix:** type it as `number | null`, and render it as a local date-time using a shared formatter in `shared.ts`, plus "(in 1h 00m)" through the existing duration formatter.
   - **Vitest:** a fixture response with an epoch value renders a formatted time, not the digits.
3. **The audit time filters need a timezone contract.**
   - `since`/`until` are parsed as `datetime` and compared with the tz-aware `created_at`. A naive input (no offset) compares inconsistently in SQLite.
   - **Fix:** reject naive `since`/`until` with 422 ("include a timezone offset"), and normalize aware values to UTC before comparing. Make sure the web page sends ISO with an offset (e.g. `toISOString()`).
   - **ASGI tests:**
     - naive gives 422
     - `+02:00` and `Z` inputs select the same rows as their UTC equivalents, including an event exactly on the boundary

## Evidence (the report is rejected without it)
- A table mapping items 1–3 to their tests, with the failing line before the fix and the passing line after.
- `just check` green (pytest and Vitest counts, web branch coverage ≥ 81 %), `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19h. **Parallel engineers:** M19f is in `api/deps.py`, `api/routes/admin.py`, `config/history.py` and `api/app.py`; M19g is in `logging.py` and a support/logs route. Don't touch those.
