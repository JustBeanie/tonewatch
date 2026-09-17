# Brief: M19d — M19.8 credential management (backend + API)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19d` (branch `m19d`). **E2E port:** `TONEWATCH_E2E_PORT=8838`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 (~line 650) and M19.8.
- `backend/src/tonewatch/api/auth.py`: `token_path`, the existing `rotate_token`, sessions, `ui_password` hashing, CSRF.
- `api/routes/auth.py`.
- The live-stream secret, in `streaming/` or `api/routes/live.py` (created on first use, owner-only permissions).
- `api/audit.py` `record_audit`.
- `docs/security/threat-model/`.

## Required (backend and API only; the UI is a later slice)
All endpoints live under `/api/admin/credentials/...`. Each one requires `write_auth` (auth + CSRF for cookie sessions), writes an audit event, and **never returns or logs a secret except the one new API token, returned once**. Mark responses `Cache-Control: no-store`.

1. **Rotate API token:** `POST /api/admin/credentials/api-token/rotate` with body `{grace_seconds: 0..86400, default 3600}`.
   - It writes the new token atomically with owner-only permissions and returns `{token, previous_valid_until}` exactly once.
   - The old token stays valid until the grace period ends, then is rejected. This covers bearer, WS subprotocol and any other place the token is accepted.
   - The grace state is persisted, so a restart during grace keeps the old token valid until expiry, and never longer.
   - A second rotation during grace invalidates the first old token immediately; only one previous token is ever valid.
2. **Rotate live-stream secret:** `POST /api/admin/credentials/live-secret/rotate`. All existing live URLs are rejected immediately, and active listeners are disconnected cleanly. Returns `{ok: true}`.
3. **Change UI password:** `POST /api/admin/credentials/ui-password` with body `{current_password, new_password}`.
   - The new password needs at least 12 characters, and the endpoint is rate-limited.
   - The current password must verify; a wrong one gives 403, which is audited with no password in the audit row.
   - On success, all **other** sessions are revoked, and the caller's session stays valid (or is reissued; document which).
   - If no UI password is configured, the endpoint sets one only when the caller authenticated with the API token. Document this.
4. **Revoke all sessions:** `POST /api/admin/credentials/sessions/revoke-all`. Every cookie session, including the caller's, becomes invalid. API token auth is unaffected.
5. **Add-on/ingress mode:** document and test what's allowed. The trusted ingress bypass must not allow rotating the API token without CSRF protection.
6. **Threat model and docs:** add rows (token rotation, grace window, session revocation) and `docs/guide/admin.md` sections.

## Mandatory tests (write first; show each failing line)
- **A.** Token rotation through ASGI: the new token works immediately. The old one works during grace and fails after it (injected clock). A restart mid-grace, simulated by recreating the app from the same data dir, keeps the old token valid until expiry. A double rotation kills the first old token. The response has `no-store`, and the token appears in no log (`caplog`) or audit row.
- **B.** Live secret rotation: a previously issued live URL gives 401/403, a fresh URL works, and an active fake listener is closed.
- **C.** UI password: wrong current password gives 403 with the audit row free of both passwords. A short new password gives 422. On success, other sessions are rejected and the caller continues (or is reissued), and a login with the new password works. The rate limit gives 429.
- **D.** Revoke all: every cookie session is rejected, and bearer still works.
- **E.** Auth matrix for every endpoint: no auth gives 401, a cookie without CSRF gives 403, and ingress mode follows the documented rule.
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty. If an S4 test blocks you, report it and stop.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its failing and passing lines.
- `just check` (pytest before and after; coverage for api and auth), then `just ci-local` up to `api-drift` (run `just gen-api`).
- `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.8 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real sockets in tests.
- **Parallel engineers:** M19c is working in `web/**` (admin pages) and M19e in maintenance/metrics (`recording/retention.py`, `storage/`, and a new metrics route). Don't touch those areas. If you must register a router in `api/app.py`, keep that edit minimal.
