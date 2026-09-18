# Brief: M19d-fix — close the legacy rotation bypass, fix log redaction after rotation, and make tests A–E prove the contract

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b014-b64b-7ab3-bc5d-2da3611a5b37`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19d` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8838`. `docs/pm/briefs/M19d-credentials.md` still applies in full.

## PM review findings
Your implementation is a reasonable start, but the review found real defects, and the tests don't prove most of the brief. **Your report also had no test-to-letter table with failing and passing lines, which the brief requires.**

### Bugs (write a failing test first for each, then fix)
1. **The legacy rotation endpoint bypasses everything.**
   - `POST /api/auth/token/rotate` (`api/routes/auth.py` ~line 93) still calls `rotate_token(settings)` and sets `auth.token` directly, and it uses `_write_auth`, so the trusted ingress bypass can rotate the API token with no CSRF (brief item 5).
   - It also leaves any existing `api_token_grace` state valid, so a previous token stays alive, and it never returns the new token, which locks the caller out.
   - **Fix:** remove this endpoint (regenerate the API client and update docs), or make it a thin alias that goes through `credential_write_auth` and `AuthState.rotate_api_token`. Removal is preferred; check `web/src` for callers first and report what you find.
   - **Tests:**
     - Ingress can't rotate through **any** path.
     - After rotation through any remaining path, at most one previous token is valid.
2. **Log redaction keeps only the startup token.**
   - `configure_logging(api_token=auth.token)` stores the token in a ContextVar once. After rotation, the **new** token (and the grace-period previous token) are not redacted from logs.
   - **Fix:** redaction must read the live current and previous tokens, e.g. a small mutable holder that `AuthState` updates on rotation. A ContextVar set once in `create_app` is not enough.
   - **Test:** rotate, then log a message containing the new token and the old token with `caplog`/structlog capture. Neither value appears.
3. **The WebSocket subprotocol token check uses `==`**, and token matching is copy-pasted three times (`auth.py` `bearer_valid`, `ws.py` header branch, `ws.py` subprotocol branch).
   - **Fix:** add one `AuthState.token_matches(supplied: str) -> bool` using `hmac.compare_digest` for current and in-grace previous tokens, and use it everywhere, including `routes/auth.py` status.
   - **Test:** a WS connection with the old token through the subprotocol works during grace and is rejected after it.
4. **UI password set when none is configured:** a bearer caller omitting `current_password` gets 403, but the docs say bearer can set it. Accept an absent **or** empty `current_password` in that case, and test both.

### Cleanups
- Revert the unrelated churn in `api/app.py`: the deleted `input_devices` docstring and the `engine, sessions = None, session_factory` rewrite.
- `routes/credentials.py` uses `__import__("tempfile")` and duplicates the atomic write. Make `auth.py`'s atomic writer a shared helper that handles bytes, and use it for the live secret.
- Import `credentials_router` in `api/app.py` directly from `api/routes/credentials.py`, not re-exported through `routes/admin.py`.

### Tests that don't prove the brief (rewrite them)
All tests currently pass `session_factory=lambda: None`, so `record_audit` returns early and **no audit row is ever checked**. Use a real temporary SQLite session factory, as the existing audit tests do.
- **A. Token rotation:**
  - **Restart mid-grace:** recreate the app at `now=1005` (inside grace) and assert the old token is **still 200**, then at `1011` assert 401. The current test only restarts after expiry.
  - **Double rotation:** rotate twice, then assert the first old token is 401 immediately, the second old token is 200 in grace, and the newest token is 200.
  - `grace_seconds: 0` makes the old token 401 immediately. `-1`, `86401`, `true` and `"60"` give 422.
  - **No leaks:** neither the token nor the previous token appears in any audit row (query the table) or in captured logs.
- **B. Live secret:** also assert a freshly issued URL after rotation is **200** (or streams), not only that the old one is 401. Assert an audit row exists.
- **C. UI password:**
  - The wrong-password audit row exists and contains neither password; scan the whole serialized row.
  - Document and test whether the caller's session is kept or reissued.
  - The rate limit is per client and resets on success; test that the 429 is reached **before** a correct password would work, so a correct password after lockout is still 429 inside the window.
- **D. Revoke all:** the caller's own session is rejected afterwards, bearer still works, and an audit row exists.
- **E. Auth matrix, parametrized over all four endpoints:**
  - no auth gives 401
  - a **valid** session cookie without the CSRF header gives 403 (the current test uses a nonexistent session, which only tests 401)
  - trusted ingress (add-on mode from the Supervisor IP, as in `test_api_security.py` ~line 146) gives 403
  - bearer succeeds

## Evidence (the report is rejected without it)
- A table mapping each test to its letter or bug number, with its **failing line before the fix** and its passing line after. For tests that passed immediately against your existing code, say so.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api` at least 1 % above the gate.
- `just ci-local` up to `api-drift` (run `just gen-api`), and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19d. **Parallel engineer M19e** is in retention, storage, maintenance routes and `/metrics`. M19c (web admin pages) has landed on main. Don't touch `web/**` except the generated client, and only touch `api/app.py` minimally.
