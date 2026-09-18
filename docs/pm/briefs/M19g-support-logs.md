# Brief: M19g — M19.7 support bundle and log viewer (backend + API)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19g` (branch `m19g`). **E2E port:** `TONEWATCH_E2E_PORT=8844`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro and **M19.7** (~line 684).
- `logging.py` in full: `_redact`, `SecretHolder` (API-token redaction that follows rotation), `is_sensitive_log_key`, `_redact_query`, and the file/stream handlers.
- `api/routes/admin.py` `health()`; `api/audit.py` `mask_secrets`; the CAD models (incident addresses are sensitive).
- `docs/security/threat-model/`.

## Required (backend and API only)
1. **In-memory log ring.**
   - A bounded ring buffer of the last N (default 2000) **already-redacted, rendered** structured log records, fed by a handler on the root logger **after** the redaction processor. It must never hold pre-redaction data.
   - Bound it by record count and by a per-record size cap (truncate long messages, and say so in the record).
   - Handler failures must never break logging.
2. **Log viewer API:** `GET /api/admin/logs?level=&since_seq=&limit=` (limit ≤ 500). It returns records with a monotonic `seq`, time, level, logger, event and a bounded set of fields, filtered by minimum level. `since_seq` enables tailing. It uses `authenticated` and `Cache-Control: no-store`.
3. **Support bundle:** `POST /api/admin/support-bundle` returns a zip download.
   - It uses `write_auth`, is audited, rate-limited (1 per 30 s) and sent with `no-store`.
   - Contents:
     - `manifest.json`: versions, time, and the file list with SHA-256
     - `config.redacted.yaml`: masked **and** with CAD/agency addresses, URL credentials, webhook URLs and MQTT hosts reduced to `[REDACTED]` or a host-class hint
     - `health.json`
     - `logs.jsonl` from the ring
     - `detections.json`: the last N (default 50) call summaries: time, tone set id, duration and outcome counts, **no addresses, no incident text, no recording paths**
     - `environment.json`: OS, Python and package versions, add-on/Windows/Docker mode; **no environment variables**
   - **No recordings, no secrets, no addresses**, with no opt-in in this slice.
   - Build the zip in memory or a temp file with a total size cap, and never follow a symlink.

## Mandatory tests (write first; show each failing line)
- **A. Ring redaction:** log an event containing the API token, a rotated new token (use `AuthState.rotate_api_token`), a `password=` field, a URL with `?t=` and a Meshtastic PSK-shaped key. The ring and the API show none of them. The ring stays bounded after 5000 records, and a 1 MB message is truncated.
- **B. Log API:**
  - level filtering works
  - `since_seq` returns only newer records
  - `limit` above 500 gives 422
  - no auth gives 401
- **C. Bundle secrecy.** Build a fixture config with every secret-bearing field that exists (grep what `is_secret_key` matches: webhook URLs with credentials, MQTT password, Meshtastic PSK, CAD feed credentials) and seed a CAD incident with an address plus a call with a recording path. Then unzip the bundle and scan **every file** for each fixture secret, the address, the recording path and the data dir absolute path. None may appear.
- **D. Bundle structure:** the manifest checksums match the files, it's audited, a second call inside 30 s gives 429, a cookie without CSRF gives 403, ingress follows the rule you document, and `no-store` is set.
- **E.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` fully green, with every `check_package_coverage.py` line at least 1 % above its gate. Then `just ci-local` up to `api-drift` (run `just gen-api`). `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.7 `[~] ... — PENDING-REVIEW`.
- No new dependencies (use `zipfile`). No subdirectory `conftest.py`. Never weaken a gate. No real incident data.
- Add a threat-model row with id **TM-049** (the parallel engineer M19f takes TM-048) and a `docs/guide/admin.md` section.
- **Parallel engineer M19f** works in `config/store.py`, `api/routes/config.py` and a new config-history route. Don't touch those. Keep any `api/app.py` edit to one router registration.
