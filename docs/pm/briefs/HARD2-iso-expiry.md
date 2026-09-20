# Brief: HARD2 — return the token grace expiry as ISO 8601, not a Unix epoch (DAST warning)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-hard2` (branch `hard2`). **E2E port:** `TONEWATCH_E2E_PORT=8864`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem
After HARD1 fixed the 500s, the Docker workflow's `dast` job still fails. The ZAP API scan now reports:

```
WARN-NEW: Timestamp Disclosure - Unix [10096] x 2
  http://127.0.0.1:8099/api/auth/token/rotate (200 OK)
  http://127.0.0.1:8099/api/admin/credentials/api-token/rotate (200 OK)
zap-baseline exit=0 zap-api-scan exit=2  (the job treats a WARN as failure)
5xx responses during scans: 0
```

Both endpoints return `previous_valid_until` as a Unix epoch integer (`AuthState.rotate_api_token` in `api/auth.py`). **Do not add a ZAP ignore rule** in `docker/zap/rules.tsv`: fix the API.

## Required
1. **API:** return `previous_valid_until` as an **ISO 8601 UTC timestamp string** (e.g. `2026-09-19T02:38:17Z`), or `null` when the grace period is zero, from both `POST /api/admin/credentials/api-token/rotate` and the legacy `POST /api/auth/token/rotate`. Keep the internal epoch representation for expiry maths and the persisted grace file; only the response shape changes. Run `just gen-api`.
2. **Web:** `web/src/features/admin/Credentials.tsx` currently formats an epoch number. Update it to parse the ISO string, keeping the same rendering (a local date-time plus the remaining duration), and update its Vitest.
3. **Grep for any other Unix epoch in an API response** (`api/routes/**`) and report what you find. Convert any that are plain seconds-since-epoch in a JSON body to ISO 8601, unless the value is a duration or an uptime in seconds, which are fine. The `/metrics` Prometheus body is exempt: that format uses numbers by design. Say in your report what you changed and what you left.
4. **Tests:**
   - the rotate response matches an ISO 8601 UTC pattern and round-trips to the same instant as the internal expiry
   - a zero grace period gives `null`
   - the old token still works before the expiry and fails after it, through the injected clock, unchanged
   - the web test renders the formatted value from an ISO string

## Evidence (the report is rejected without it)
- A table for items 1, 2 and 4, with the failing line before the fix and the passing line after.
- The item 3 grep result, listing every candidate and your decision on it.
- `just check` fully green with the pytest and Vitest counts, plus the `check_package_coverage.py` lines for `api` at least 1 % above the gates.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**`, `PLAN.md` or `backend/tests/unit/test_s4_security.py`. No new dependencies. Never weaken a gate, and never add a DAST ignore.
- Nothing else is running right now; you own the worktree.
