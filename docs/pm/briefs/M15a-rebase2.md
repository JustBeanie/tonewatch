# Brief: M15a-rebase2 — resolve squelch conflicts (PM already did the git steps)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a09968-2163-7eb3-b3e5-8a30671139fa`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a`. **E2E port:** `TONEWATCH_E2E_PORT=8803` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## What changed since your last run
- Your sandbox can't write git metadata for a linked worktree, which is expected, so **the PM ran the git steps for you:**
  - backup to `Proj/pm-backups/m15a-premerge-*`
  - `git stash push -u` → `git merge --ff-only origin/main` (HEAD is now `0b2c157`, which includes M14a) → `git stash pop`, then `git reset` to clear the unmerged index
- **Your M15a changes are now applied on top of main.** Most files merged cleanly. **Three files contain conflict markers** (`<<<<<<<`/`=======`/`>>>>>>>`):
  - `backend/src/tonewatch/api/routes/config.py`
  - `backend/src/tonewatch/config/models.py`
  - `backend/src/tonewatch/pipeline/channel.py`
- `dsp/squelch.py` and `tests/unit/test_squelch.py` are untracked and present.
- **Don't run any git command that writes:** no fetch, stash, merge, rebase, checkout, reset, add or commit. Read-only `git diff`/`git status`/`git show origin/main:<path>` is fine.

## Required
Items 2–5 of the M15a-rebase brief still apply; they are repeated here.
1. **Resolve every conflict marker, keeping both features:**
   - **Source status** (`config.py`) returns `squelch_open`, `last_activity_at` **and** `live_listeners`. All three are `null` when the supervisor is absent; `live_hub` may also be absent.
   - **`SourceBase`** has both `squelch: SquelchConfig` (with your int-migration validator) and `live_stream_enabled`.
   - **`Channel`** keeps M14a's `live_hub` param and `_feed_live`, plus all your squelch wiring (level, watchdog, `stop_on_squelch`, `SquelchChanged`).
   - Afterwards, `grep -rn '^<<<<<<<\|^>>>>>>>' backend web docs` must print nothing (paste it).
   - Check that the clean auto-merges also compiled correctly, especially `dispatcher.py`, `supervisor.py`, `events.py`, `watchdog.py` and the importer/add-on `AppConfig` rebuilds (they must keep `live_stream=`).
2. **Wire the squelch gate into the live stream (PLAN M15.3):**
   - `_feed_live(..., gate_open=...)` is `True` when squelch mode is `off`; otherwise it follows the software squelch state.
   - Detection stays ungated.
   - **Test through `Channel`** with a fake live hub that records `gate_open`: mode off is always `True`; level mode follows transitions; `ToneDetected` timing is unchanged versus mode off.
3. **Regenerate the web client** (`just gen-api`).
   - Resolve `docs/PROGRESS.md` if needed: keep main's M14 `[x]` rows and your M15 rows.
   - Re-derive any ASVS checklist line anchors your rows reference: quote-all CSV, LF, line = newline count before the unique snippet.
4. **Gates:** `just check`, then `just e2e` (port 8803), then `just ci-local`. api-drift may fail only on uncommitted generated files; paste `git diff --stat -- web/src/api`.

## Evidence
- Each conflicted file with a one-line resolution summary.
- The red-first and passing lines for the new live-gate test.
- The pytest count, which must be at least main's M14a count (421 passed + 3 skipped at `c0e2305`) plus your M15 tests. State both numbers.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py` must be empty.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate or edit existing security tests.
- Never write git state. Don't describe work you haven't done.
