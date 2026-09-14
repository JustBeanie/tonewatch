# Brief: M15a-rebase — rebase reviewed squelch work onto main (after M14a landed)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a09968-2163-7eb3-b3e5-8a30671139fa`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a`. **E2E port:** `TONEWATCH_E2E_PORT=8803` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Context
- **Your M15a work passed PM review** (M15a-fix2-resume): requirements 1–9 are verified with tests; 422 passed.
- **Since your base, `origin/main` gained the M14a live restream,** which touches the same files:
  - `pipeline/channel.py` (a `live_hub` parameter, and `_feed_live` called per frame with `gate_open=True`)
  - `pipeline/supervisor.py` (`live_hub` passed to channels)
  - `config/models.py` (`LiveStreamConfig`, `AppConfig.live_stream`, `SourceBase.live_stream_enabled`)
  - `api/routes/config.py` (source list/detail add `live_listeners`)
  - `api/app.py`, `api/deps.py`, `events.py` (`LiveListenersChanged`), `logging.py`
  - the importer and add-on supervisor (`AppConfig` rebuilds pass `live_stream=`)
  - the generated web API files, `docs/PROGRESS.md`, and `docs/security/*`

## Required
1. **Back up first.** `git diff --binary > <tmp>/m15a.diff` plus a tar of untracked files. Use a `/c/Users/...` path and `tar --force-local`.
2. **Bring the worktree onto `origin/main`,** keeping your changes. Either `git stash push -u` → `git merge --ff-only origin/main` → `git stash pop`, or an equivalent. Resolve every conflict **keeping both features**:
   - **Source status** in `config.py` returns **both** `squelch_open`/`last_activity_at` **and** `live_listeners`, with your supervisor-less `null` guard applied to all three (`live_hub` may also be absent).
   - **`SourceBase`** gets both `squelch: SquelchConfig` and `live_stream_enabled`.
   - **Every `AppConfig(...)` rebuild** (importer, add-on supervisor, deps, config routes) keeps `live_stream=` and doesn't drop any field.
3. **Wire the squelch gate into the live stream,** which is PLAN M15.3 and what M14 anticipated. In `Channel`, `_feed_live` must pass `gate_open=` the software squelch state. Open when mode is `off`. When mode is not off, open only while squelch is open. The live stream then carries silence while squelch is closed. **Detection stays ungated.**
   - **Test through `Channel`** with a fake live hub recording `gate_open`: mode off always gives `True`; level mode follows the squelch transitions. Also check that `ToneDetected` timing is unchanged.
4. **Regenerate** the web client (`just gen-api`). **Resolve `docs/PROGRESS.md`** by keeping main's M14 `[x]` rows and your M15 rows. **Re-derive** any ASVS checklist line anchors your rows reference, following the existing conventions (quote-all CSV, LF, line = newline count before the unique snippet).
5. **Gates:** `just check`, then `just e2e` (port 8803), then `just ci-local`. api-drift may fail only on uncommitted generated files; paste `git diff --stat -- web/src/api`.

## Evidence
- Paste every conflicted file with a one-line resolution summary.
- Paste the red-first and passing lines for the new gate test.
- State the pytest count, which must be at least M14a main's count plus your M15 tests; state both numbers.
- Paste `git diff origin/main -- backend/tests/unit/test_s4_security.py`, which must be empty.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate or edit existing security tests.
- Never `git add`, commit or push.
- Don't describe work you haven't done.
