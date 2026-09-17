# Brief: M19e — M19.9 maintenance and M19.10 Prometheus metrics (backend + API)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19e` (branch `m19e`). **E2E port:** `TONEWATCH_E2E_PORT=8840`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19.9 and M19.10 (~lines 688–690).
- `recording/retention.py`, including CAD retention from M17a.
- `storage/db.py` and `storage/models.py`.
- `admin/health.py`, which already computes realtime factor, drops, event bus lag, disk and outputs.
- `api/routes/admin.py`.
- `settings.py`, for how opt-in features are configured.

## Required (backend and API only)
### M19.9 Maintenance
All endpoints live under `/api/admin/maintenance/...`, use `write_auth` and write an audit event.
1. **Retention dry-run:** `POST .../retention/preview` returns `{recordings: {files, bytes}, calls, cad_incidents, discovered}`, exactly what the current policy **would** delete, computed by the same code path as the real run. It deletes nothing. Refactor `retention.enforce` into plan then apply, so preview and run can't disagree.
2. **Retention run-now:** `POST .../retention/run` runs the same plan and returns the counts. Only one run at a time: a concurrent call gives 409. It must not race the daily retention job; share a lock.
3. **SQLite checkpoint and vacuum:** `POST .../database/checkpoint` (WAL `TRUNCATE`) and `POST .../database/vacuum`.
   - Vacuum refuses (409) while retention or another maintenance task runs, and returns before/after file sizes.
   - Both run without blocking the event loop (a thread or the async driver) and stay safe while the pipeline writes. Serialize writers or document why it's safe.
4. **Orphan cleanup:**
   - `POST .../orphans/preview` lists recording files under the recordings root with no DB row, and `Recording` rows whose file is missing, with counts and bytes (capped at 1000 listed; relative paths only).
   - `POST .../orphans/apply` with `{delete_files: bool, delete_rows: bool, expected_counts}` refuses (409) if the counts changed since preview.
   - **Path safety:** only files strictly inside the recordings root; symlinks are never followed out of the root.

### M19.10 Prometheus `/metrics`
5. Add `GET /metrics`, **off by default** via a new `metrics.enabled` config or setting; the endpoint returns 404 when disabled. When enabled, it requires the API token (bearer); cookie sessions and ingress are **not** accepted. Output is the Prometheus text format, written by hand (**no new dependency**).
   - Metrics, with bounded label cardinality (source_id, target_id, toneset_id only from configured ids, never free text):
     - `tonewatch_detections_total{toneset_id}`
     - `tonewatch_alert_attempts_total{target_id,phase,outcome}`
     - `tonewatch_feed_healthy{source_id}`
     - `tonewatch_realtime_factor{source_id}`
     - `tonewatch_frames_dropped_total{source_id}`
     - `tonewatch_eventbus_queue_depth{subscriber}`
     - `tonewatch_disk_free_bytes`
     - `tonewatch_db_size_bytes`
     - `tonewatch_cad_feed_connected{feed_id}`
     - `tonewatch_build_info{version}` = 1
   - Label values are escaped per the exposition format. **No** addresses, incident fields, URLs or secrets in any label or value.
   - Document it in `docs/guide/admin.md`, with a Prometheus scrape config example, and add a threat model row.

## Mandatory tests (write first; show each failing line)
- **A.** Preview equals run: seeded old recordings, calls and CAD rows give preview counts **equal** to the run's counts, and after the run a second preview shows zero. Concurrent run gives 409.
- **B.** Checkpoint and vacuum on a real SQLite file with WAL: sizes are reported, and vacuum during a retention run gives 409.
- **C.** Orphans: an orphan file plus a missing-file row are previewed. Apply with stale `expected_counts` gives 409. Apply deletes exactly those. A symlink pointing outside the root is not listed or deleted, and a `../` path in a DB row is rejected.
- **D.** Auth matrix for maintenance: 401 without auth, 403 for a cookie without CSRF, and an audit row per action.
- **E.** Metrics:
  - disabled gives 404
  - enabled with no token gives 401, and a cookie session gives 401
  - with the bearer token: 200, `text/plain; version=0.0.4`, and golden output for a fixture health snapshot
  - label escaping of `"` and `\`
  - a scan proving no address, URL or secret string from the fixture config appears
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its failing and passing lines.
- `just check`, with **every package coverage line at least 1 % above its gate** (Linux CI measures slightly lower than the Windows host), then `just ci-local` up to `api-drift`. `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.9 and M19.10 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real sockets.
- **Parallel engineers:** M19c is in `web/**`, and M19d is in `api/auth.py`, `api/routes/auth.py`, the live secret and a new credentials route. Don't touch those. Keep any `api/app.py` edit minimal.
