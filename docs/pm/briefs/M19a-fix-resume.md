# Brief: M19a-fix-resume — finish the interrupted run (gates only)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a2bd-e3ef-70a0-b50c-6b14c1ada888`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19a`. **E2E port:** `TONEWATCH_E2E_PORT=8808` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. Keep using `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** never write git state.

## What happened
Your previous run was **killed by a host/session restart at 20:56**, part-way through `just check` (`code-mode host closed its stdout`). Nothing is wrong with your work; it simply stopped.

**Your edits survived in the worktree**, including:
- `backend/tests/unit/test_m19a_admin_health.py` (10 tests)
- `backend/tests/integration/test_m19a_admin_api.py` (6 tests)
- `admin/health.py`, `api/routes/admin.py`, migration `0006`, repository and hook changes, docs.

## Required
1. **Re-run the gates and finish the job.** Nothing needs rewriting unless a gate fails.
   - `just check` must pass, including **every coverage gate** (`api/routes/admin.py` and `admin/health.py` were previously 55 %; alerts needed 90 %). Add tests rather than lowering a gate or adding `pragma: no cover`.
   - Then `just e2e` (port 8808). If the launcher hangs after the 4 specs pass, paste that line and continue.
   - Then `just ci-local` up to api-drift; run `just gen-api` if generated files drift.
2. **Confirm the mandatory list is complete.** Check your tests against `docs/pm/briefs/M19a-admin-health.md` items A–K plus item 3 (hook regressions). If any letter is missing, add it now. Your current names cover A–K, but verify each actually asserts what the letter requires, especially:
   - **E**: the disk scan runs in a thread and is cached for 60 s.
   - **I**: the full retry matrix (409 succeeded / call missing / target gone, 404 unknown, 429 concurrent, 403 without CSRF, 401 without auth, target-timeout, Meshtastic `rate_limited` row).
   - **J**: migration upgrade → downgrade → upgrade keeps rows and defaults `retry` false.

## Evidence
- A table: test name → letter (A–K, item 3).
- The pytest count: 531 at the base, N now.
- Coverage lines for `api/routes/admin.py`, `admin/health.py` and alerts.
- `just check`, `just e2e`, `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate or coverage threshold.
- No new dependencies. Never write git state. Don't describe work you haven't done.
