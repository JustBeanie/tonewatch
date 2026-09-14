# Brief: M15b-fix — auto squelch: resolve conflicts over agencies, add the missing mandatory tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1fb-07d0-7af0-8e35-4680625b6bf4`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15b`. **E2E port:** `TONEWATCH_E2E_PORT=8807` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, add `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** never write git state (no fetch, stash, merge, reset, add or commit). Read-only diff/show is fine.

## Verdict on M15b: FAIL (tests + evidence)
**PM verified and kept:**
- The `mode: "auto"` fields and bounds, plus the `auto_min_samples_s ≤ auto_window_s` validator.
- The shared percentile helper, and the estimator using `auto_k` and the margin clamps.
- Calibrating fail-open (initial `open = True` in auto).
- `SquelchHealthChanged`, the `squelch_calibrated` audit event and the calibrate route.
- `test_squelch.py` changes are additions only (the one removed line was an import line being replaced).
- Tests A–G exist:
  - `test_auto_open_is_monotonic_in_floor_and_margin_is_bounded`
  - `test_auto_close_is_at_least_three_db_below_open`
  - `test_auto_busy_channel_floor_tracks_true_floor`
  - `test_auto_calibrating_fails_open_then_uses_thresholds`
  - `test_auto_stuck_open_health_sets_and_clears_once`
  - `test_auto_chatter_doubles_hang_and_clears_after_calm_period`
  - `test_shared_percentile_helper_preserves_noise_floor_result`

**Why it fails:**
- **Missing tests:** mandatory tests **H, I and J** are absent. **K** is incomplete: the two calibrate tests call `calibrate_squelch` directly, so auth (401), CSRF (403), 422 via request validation, and the real routing are untested.
- **Missing evidence:** there is no test map, no red-first evidence, no baseline pytest count, and `ci-local` wasn't run.

## The PM already did the git steps
- `main` gained **M16a agencies** (`8d4b5b5`). The PM ran: backup to `Proj/pm-backups/m15b-premerge-*`, `stash -u`, `ff-only` to `8d4b5b5`, `stash pop`, then `git reset`.
- **3 files contain conflict markers:**
  - `backend/src/tonewatch/api/routes/config.py` (1)
  - `docs/security/threat-model/README.md` (1)
  - `docs/security/threat-model/tonewatch.json` (1)

## Required
1. **Resolve every marker, keeping both features:**
   - **`config.py`:** keep main's `rebuild_config` (the `replace_config` helper) for every config rebuild, plus the source status fields `squelch_open`, `last_activity_at`, `live_listeners`, **and** your calibrate route and 8 diagnostic fields.
   - **Threat model:** keep both sides' threats with unique IDs, keep the README in sync, and keep the JSON valid.
   - Then check the clean auto-merges: `channel.py` must keep `agency_lookup`, `live_hub`/`_feed_live` and your auto diagnostics, and `supervisor.py` must still pass `agency_lookup` late-bound.
   - The marker grep `grep -rn '^<<<<<<<\|^=======$\|^>>>>>>>' backend web/src docs mkdocs.yml` must print nothing (paste it).
   - Run `just gen-api` after resolving.
2. **Add the missing tests**, as specified in the M15b brief:
   - **H. Config:**
     - A pre-M15b YAML fixture (source squelch without any auto keys) loads unchanged.
     - `auto_min_samples_s > auto_window_s` returns 422 through `POST /api/sources`, naming the field.
     - `max_margin_db < min_margin_db` returns 422 the same way. If that validator doesn't exist yet, add it; it was required.
   - **I. Channel:** through `Channel` with a fake live hub in `mode="auto"`:
     - calibrating → `gate_open=True`
     - after `auto_min_samples_s`, gate values follow thresholds
     - `ToneDetected` times identical to mode `off`
   - **J. Diagnostics:**
     - The source list and detail status include all 8 fields (`squelch_mode_effective`, `noise_floor_dbfs`, `open_dbfs_effective`, `close_dbfs_effective`, `calibrating`, `stuck_open`, `chatter`, `transitions_per_min`) with correct values for a running fake channel, and `null` without a supervisor.
     - The WS level message includes them.
   - **K. Calibrate via the ASGI app** (httpx `ASGITransport`, real auth), with a fake running channel emitting known levels:
     - 200 with the exact suggestion, and a second call identical (±1 dB)
     - 401 without a token; 403 on a cookie session without CSRF (follow the existing CSRF test pattern)
     - 404 unknown source; 409 source not running
     - 422 for `seconds=4` and `seconds=121`; 429 for a concurrent calibration
     - exactly one `squelch_calibrated` audit row
     - the channel tap count back to 0 after success **and** after a cancelled request
   - **Placement:** keep the existing direct-call tests only if they add value, and put the ASGI tests in `backend/tests/integration/`.
3. **Merged-feature regression:** one `Channel` test with an agency-linked tone set, auto squelch and a fake live hub. `ToneDetected.agency` is populated, the gate follows auto, and detection times are unchanged.

## Evidence (the report is rejected without this)
- Each conflicted file with a one-line resolution summary, and the empty marker grep.
- A table mapping every test to its letter, A–L plus item 3.
- For H–K and item 3, the first-run failing or passing line. For a test that passes immediately, say so explicitly.
- The pytest count on `main` (**484 passed + 3 skipped** at `8d4b5b5`) and after.
- **`just ci-local` must be run** up to api-drift. The known Windows Playwright teardown hang doesn't excuse skipping it: if e2e hangs after the 4 specs pass, paste that line and continue with the remaining stages (`just lint typecheck test test-web` plus the security recipe). Paste `git diff --stat -- web/src/api`.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py` must be empty.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification. dsp/pipeline coverage stays at or above 95%.
- Synthetic levels only; no real radio data.
- Never write git state. Don't describe work you haven't done.
