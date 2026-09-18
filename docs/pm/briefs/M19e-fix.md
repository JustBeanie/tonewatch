# Brief: M19e-fix — orphan cleanup can delete live recordings, and the metrics tests are shaped to the code instead of reality

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b014-c9cf-70b2-a860-a9c9073dc9c3`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19e` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8840`. `docs/pm/briefs/M19e-maintenance-metrics.md` and `M19e-tests.md` still apply.

## PM review
Coverage is good now. But the review found bugs your tests missed, because several tests use fixture values that match the code instead of what production produces. **Your report again lacked a failing line per test and whether each passed immediately.** For this round, every item below needs a test that **fails on your current code** first; paste that failing line.

### Bugs
1. **Orphan cleanup races the recorder and can delete real recordings (data loss).**
   - `recording/encoder.py` ~line 73 writes `.<call_id>.*.<ext>.tmp` under the recordings root, then renames it to the final path.
   - `pipeline/persistence.py` ~line 370 inserts the `Recording` row only **after** that rename plus an awaited `_recording_facts`.
   - So during an active call, orphans preview/apply sees the `.tmp` file, or the final file before its row exists, as an orphan. `apply` with matching counts deletes it.
   - **Fix:**
     - Never list or delete `*.tmp` files or dot-prefixed temp files.
     - Never list or delete any file whose mtime is newer than a safety age (e.g. `max(3600, max recording duration + 300)` seconds; take it from config/settings, documented).
     - In `apply`, re-check each candidate right before unlinking: it must still be unknown to the DB, not a symlink, inside the root, and older than the safety age.
   - The same safety age applies to **missing-file rows**: a row created within the window is not reported or deleted.
   - **Tests** (use an injected clock or `os.utime`):
     - a fresh `.tmp`, and a fresh final file with no row, are neither listed nor deleted
     - an old orphan is deleted
     - a file that gains a DB row between preview and apply is not deleted (apply gives 409 or skips it; document which)
2. **One bad DB path breaks orphan maintenance forever.**
   - `_recording_path` raises 422 inside preview and apply, so a single row with `../` makes both endpoints fail permanently.
   - **Fix:** report such rows as `invalid_rows: [{id}]` (no path echoed), never delete them or anything they point at, and keep processing the rest.
   - **Test:** one traversal row plus one real orphan: preview is 200, lists the orphan, and reports the invalid row id. Apply deletes the orphan only, and the traversal target file outside the root still exists.
3. **Metrics drop real alert attempts.**
   - `render_metrics` allowlists phases `{"pre_alert", "final", "retry", "unknown"}`, but the dispatcher writes `"pre_alert"`, `"recording_ready"` and `"retry"` (`alerts/dispatcher.py`). Every `recording_ready` attempt is silently dropped, and your test seeds `phase="final"`, which production never writes.
   - **Fix:** derive the allowed phases from one constant shared with the dispatcher, or a `Literal` type used by both.
   - **Test:** seed attempts using the dispatcher's real phase constants, and assert each appears.
4. **`tonewatch_detections_total` and `tonewatch_alert_attempts_total` are not counters.**
   - They are `COUNT(*)` over DB rows, so retention deletes make them **decrease**. Prometheus treats that as a counter reset, so `rate()`/`increase()` report a false spike.
   - **Fix:** keep process-lifetime monotonic counters in memory, incremented when a detection is persisted and when an attempt row is written (hook the existing event bus or the write sites), starting at 0 at process start. Add `# HELP` and `# TYPE` lines for every metric (`counter` or `gauge`).
   - **Tests:**
     - The counters increase on detection and attempt.
     - Running retention that deletes rows does **not** decrease them.
     - `# TYPE` lines are present.
5. **The golden test uses a hand-written snapshot, not the real health response.**
   - The response body of the real `/metrics` route is never asserted.
   - **Fix the test:** build the golden file from a real app with a fixture config (source, target, tone set, CAD feed) and a fake supervisor/health state. Assert the full body of `GET /metrics` against a golden file, normalizing only volatile values (`disk_free_bytes`, `db_size_bytes`, version). That proves the key names (`free_bytes`, `db_bytes`, `service.subscribers[].id`, `feed_health_history`, `cad_feeds[].connected`) match `api/routes/admin.py` `health()`.
   - Also assert that a CAD address, a webhook URL and target secrets from that fixture config appear nowhere in the body.
6. **Vacuum while the pipeline holds the DB.** `vacuum_database` maps busy/locked errors to `DatabaseCheckpointTimeoutError`. Make sure the route turns that into **409** (or 503) with a readable message, not a 500. **Test:** hold an open write transaction on a second connection and call the route.

### Cleanups
- In `api/app.py`, move the maintenance router import to the top-level imports next to the other routers. Keep the edit minimal; M19d also edits this file.
- The orphan preview and apply duplicate the directory walk. Extract one `scan_orphans(root, rows, now, safety_age)` function in `recording/retention.py` (or a new `recording/orphans.py`) and use it from both. That is what guarantees preview equals apply.

## Evidence (the report is rejected without it)
- A table mapping bugs 1–6 to their tests, with each **failing line on your current code** and its passing line after the fix.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api/metrics.py`, `api/routes/maintenance.py`, `recording`, `pipeline` and `alerts`, each at least 1 % above its gate.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19e. **Parallel engineer M19d** is in `api/auth.py`, `api/routes/auth.py`, `api/routes/ws.py`, `logging.py`, credentials and `streaming/live.py`. Don't touch those. `web/**` is off limits except the generated client.
