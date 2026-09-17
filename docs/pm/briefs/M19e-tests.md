# Brief: M19e-tests — write the mandatory tests A–F, fix what they expose, reach the gates

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b014-c9cf-70b2-a860-a9c9073dc9c3`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19e` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8840`. `docs/pm/briefs/M19e-maintenance-metrics.md` still applies in full.

## Status
Your honest partial report: the implementation exists (retention plan/apply, a maintenance lock, checkpoint/vacuum, maintenance routes, bearer-only `/metrics`, settings, docs), but **none of the mandatory tests A–F were written**, and `just check` fails coverage (`api/metrics.py` 18.75 %, `api/routes/maintenance.py` 27.66 %).

The brief said to write tests first. The code now exists, so these tests must be **behavioural and adversarial**, aimed at finding bugs in what you wrote, not written to match it. For each test, record whether it passed immediately or failed; for each failure, show the bug fix with file:line.

## Required (this round)
Write every mandatory test from the M19e brief:
- **A. Preview equals run:**
  - seeded old recordings, calls, CAD incidents and discovered tones: preview counts **equal** run counts
  - a second preview afterwards shows zero
  - a concurrent run gives 409
  - the daily retention loop and run-now share the lock (a test that holds the lock and asserts run-now gets 409 and the loop waits or skips)
- **B. Checkpoint and vacuum** on a real WAL SQLite file: reported before and after sizes, and vacuum while the maintenance lock is held gives 409. Prove it doesn't block the event loop, e.g. a concurrent `asyncio.sleep(0)` ticker keeps advancing.
- **C. Orphans:**
  - an orphan file and a row with a missing file are both previewed
  - apply with stale `expected_counts` gives 409
  - apply deletes exactly those
  - **a symlink pointing outside the recordings root is neither listed nor deleted** (skip only if symlink creation isn't permitted on Windows, and say so, plus add a test with a mocked `Path.resolve` that proves the root check)
  - a DB row with `../` in its path is rejected and never deleted
  - listing is capped at 1000 with relative paths only
- **D. Auth matrix** for every maintenance endpoint: 401 without auth, 403 for a cookie without CSRF, and exactly one audit row per successful action.
- **E. Metrics:**
  - disabled gives 404
  - enabled with no token gives 401
  - a cookie session gives 401
  - an ingress-trusted request gives 401
  - with bearer: 200 with content type `text/plain; version=0.0.4`, and **golden output** for a fixture health snapshot
  - `"` and `\` and newline escaped in label values
  - label cardinality: a source or target id not in config never appears
  - a scan of the output for fixture secrets, a webhook URL and a CAD address finds none of them
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, marking "passed immediately" or showing its failing line, the fix (file:line) and its passing line.
- `just check` green, with **every package coverage line at least 1 % above its gate**. Paste the `check_package_coverage.py` lines for `api/metrics.py`, `api/routes/maintenance.py`, `recording` and `pipeline`.
- `just ci-local` up to `api-drift` (run `just gen-api`), and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19e. **Parallel engineer M19d** is in `api/auth.py`, `api/routes/auth.py` and credentials. Don't touch those. M19c (web admin pages) is landing now; don't touch `web/**` except the generated client.
