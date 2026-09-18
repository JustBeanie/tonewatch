# Brief: M19f-fix — secret export must be a CSRF-protected write, history must not fail a saved config, and rollback/import require If-Match

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b5f9-6aa6-7f00-bd6c-28da6656d599`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19f` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8842`. `docs/pm/briefs/M19f-config-history.md` still applies in full.

## PM review
The core is good: history is recorded in the one shared `save_config` path, versions are masked, the diff reports secrets as `changed`, and YAML uses a safe loader. Fix the following. **Write a failing test first for each item and paste its failing line as you go**, in case your turn is cut off.

1. **Exporting secrets is a GET, so it has no CSRF protection.**
   - `GET /api/admin/config/export?include_secrets=true&confirm=include-secrets` uses `authenticated`. A cross-site top-level navigation carries the session cookie and triggers a plaintext secret download plus an audit row, with no CSRF token.
   - **Fix:** keep `GET .../export` for the **masked** export only; it rejects `include_secrets` with 422.
   - Add `POST /api/admin/config/export` with body `{format, include_secrets, confirm}`, using `write_auth` (CSRF for cookie sessions), refusing ingress for secrets, and keeping `no-store`, the attachment header, the `Warning` header and the audit.
   - **Tests:**
     - GET with `include_secrets` gives 422
     - POST with a cookie session but no CSRF header gives 403
     - POST with bearer succeeds and is audited
     - ingress gives 403
2. **A history failure turns a saved config into a 500.**
   - In `api/deps.py` `save_config`, `ConfigHistory.record` runs **after** the config file is written and hot-applied. A `HistoryError` (disk full, permissions) then returns 500 even though the change is live.
   - **Fix:** catch `HistoryError`, log a warning (no config content), and still return success. Record an audit detail `history_recorded: false`, so the operator can see it.
   - Move the `ConfigHistory` import to module level.
   - **Test:** monkeypatch `record` to raise; `PUT /api/config` returns 200, the running config changed, and the warning was logged.
3. **Rollback and import apply must require `If-Match`.**
   - `save_config` only checks the etag when the header is present, so a rollback or import without it overwrites concurrent edits silently.
   - **Fix:** for these two endpoints only (leave `PUT /api/config` behavior unchanged), a missing `If-Match` gives **428**.
   - **Tests:** missing gives 428, stale gives 412, current gives 200.
4. **The import body cap reads the whole body first.** `_parse_config_body` calls `await request.body()` and then checks the length, so a huge body is fully buffered. Bound it while streaming, e.g. extend or reuse `_TonesCfgBodyLimitMiddleware` in `api/app.py` for the two import paths. **Test:** a body 1 byte over the cap gives 413. If you can do it without a real socket, also a chunked body with no `Content-Length`.
5. **There's no baseline version, so the original config can never be rolled back to.** When the history is empty at startup, record the loaded config once, with actor `system` and route `startup`. **Test:** a fresh app lists exactly one version before any save, and restarting doesn't add another.
6. **Encapsulation:** the diff route calls `history._read`. Add a public `ConfigHistory.raw_config(version_id)`, or a `diff_against(version_id, current)`, and use it.

## Evidence (the report is rejected without it)
- A table mapping items 1–6 to their tests, with the failing line before the fix and the passing line after.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api` at least 1 % above the gate.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19f. **Parallel engineers:** M19g is in `logging.py` and a support/logs route; M19h is in `web/**` and `api/routes/audit.py`. Don't touch those. Only touch `api/app.py` where item 4 requires it, and keep that edit minimal.
