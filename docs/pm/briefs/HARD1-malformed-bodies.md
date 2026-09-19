# Brief: HARD1 — no endpoint may return 500 for a malformed request (DAST found three)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-hard1` (branch `hard1`). **E2E port:** `TONEWATCH_E2E_PORT=8860`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem
The v0.6.0 Docker workflow's ZAP DAST job (`.github/workflows/docker.yml`, the `dast` job) failed with `FAIL-NEW: Information Disclosure - Debug Error Messages [10023]` and `Application Error Disclosure [90022]`. These endpoints returned **500** on fuzzed input:
- `POST /api/admin/credentials/api-token/rotate` (including with junk query strings)
- `POST /api/admin/credentials/ui-password`
- `POST /api/admin/replay`

**Likely cause:** routes that parse the body by hand with `await request.json()` raise on a malformed, empty or non-object body. The PM's grep found these hand parsers:
- `api/routes/credentials.py:25`, `:57`
- `api/routes/replay.py:208`
- `api/routes/auth.py:37`, `:97`
- `api/routes/admin.py:147` (config import)
- `api/routes/import_tones_cfg.py:25`, `:34`

Confirm the cause for each DAST URL by reproducing it; don't assume.

## Required
1. **Reproduce first.** Write a parametrized ASGI test that sends each of these bodies to **every** POST/PUT/PATCH/DELETE route in the app, enumerated from `app.routes`, not hand-listed, with valid auth (bearer), so the request reaches the handler:
   - an empty body
   - `not json`
   - `[]`
   - `"string"`
   - `123`
   - `{"unexpected": true}`
   - a 1 MB body
   - the ZAP-style query string `?-d+allow_url_include%3d1+-d+auto_prepend_file%3dphp://input`

   Assert the status is **never ≥ 500**, and that no response body contains a traceback, an exception class name, or a file path. Paste the failing output (the list of route/body pairs that 500) before fixing.
2. **Fix at the source.**
   - Replace hand-parsed JSON bodies with Pydantic request models (FastAPI returns 422), or, where a raw body is intentional (config import YAML, tones.cfg), wrap parsing so malformed input gives a readable 400/422.
   - Keep the existing contracts: credentials' `grace_seconds` bounds, the `ui-password` rules, the replay draft validation, and the auth login shape. The generated OpenAPI changes accordingly, so run `just gen-api`.
   - Keep existing tests green. If one encodes a 500 for bad input, update it and say which.
3. **Keep DAST green:** check `.github/workflows/docker.yml` / the ZAP config for how new endpoints are scanned. Don't add ignores for these rules; the fix must make them pass. If you can run the ZAP baseline locally (the workflow may document a `just` recipe or docker command), do it and paste the summary. If you can't, say so; the PM watches CI.

## Evidence (the report is rejected without it)
- The failing matrix output before the fix (the route and body pairs that 500), and the passing run after.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api` at least 1 % above the gates.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**`, `PLAN.md` or `backend/tests/unit/test_s4_security.py`. No new dependencies. Never weaken a gate or add DAST ignores.
- **Parallel:** LEAK1 is in `backend/tests/conftest.py`; the PM is landing M19m (web). Don't touch those.
