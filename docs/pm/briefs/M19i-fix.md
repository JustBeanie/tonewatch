# Brief: M19i-fix — restore must replace only what the archive owns, detect a running instance for real, and prove rollback

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b658-aa01-7d82-81ec-d0daad4dd1ca`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19i` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8848`. `docs/pm/briefs/M19i-backup-restore.md` still applies in full.

## PM review
The archive verification is solid:
- every member is checked against the manifest
- no links or devices are allowed
- `..` and absolute paths are refused
- size caps are enforced
- extraction uses `extractfile`, never `extractall`

The online SQLite copy is correct too. But restore has a data-loss bug, the running-instance check can't work, a mandatory test is missing, and **your report had no test table with failing lines**. Write a failing test first for each item below and paste its failing line as you go, in case your turn is cut off.

1. **Restore moves the whole data dir aside, including recordings (data loss).**
   - `restore_archive` moves **every** item in `data_dir` into `pre-restore-<ts>/`. With the default `include_recordings=false`, the user's recordings disappear from their live location after a restore. Earlier `pre-restore-*` folders also get nested inside the new one, and any other files (logs, config history) vanish too.
   - Also, `settings.recording_path` can be **outside** the data dir.
   - **Fix:** restore only replaces what the archive **owns**:
     - `config.yaml`
     - `tonewatch.db` **plus its `-wal`/`-shm` siblings**, which must be moved aside too, or SQLite will replay a stale WAL onto the restored DB
     - the credential files only if the archive includes them
     - the recordings tree only if `include_recordings` is set, restored into `settings.recording_path`, not a hard-coded `data_dir/recordings`
   - Moved-aside items go to `pre-restore-<ts>/`, keeping their relative layout. Never move `pre-restore-*` folders or anything the archive doesn't own.
   - **Tests:**
     - restoring a no-recordings archive leaves existing recordings, `config-history/` and older `pre-restore-*` folders untouched
     - a stale `tonewatch.db-wal` present before restore doesn't affect the restored rows (prove it with a WAL that contains a row the backup doesn't)
     - with `include_recordings`, recordings land under `settings.recording_path`
2. **Running-instance detection doesn't work.**
   - The CLI checks for `tonewatch.lock` / `.tonewatch.lock`, but the app never creates them, and the port probe only tries `127.0.0.1`.
   - **Fix:** the server takes an **exclusive OS lock** on `data_dir/tonewatch.pid.lock` for its lifetime (in the lifespan, with the same `msvcrt`/`fcntl` pattern as `config/store.py`), writing its PID. Restore then **tries to take that lock** and refuses if it can't. Keep the port probe as a secondary check, and document both.
   - **Tests:**
     - with an app lifespan running on the data dir, restore is refused
     - after shutdown, it proceeds
     - a stale lock file with no holder doesn't block
3. **The rollback test (mandatory test D) is missing.** Monkeypatch a failure mid-swap, and separately a failing `post_apply` upgrade. Assert the data dir's **tree hash** equals the original and no staging dir is left behind.
4. **Newer-schema detection** compares numeric prefixes of revision ids. Also refuse a revision id this build doesn't know, even if its number is lower (e.g. `0005_something_else`): check it against the migration scripts' revision ids. **Test** it.
5. **Cleanup:**
   - `create_archive` uses `__import__("io").BytesIO`; import `io` normally.
   - Make sure the HTTP backup's temp file is deleted when the client disconnects mid-stream (use a background task or `finally` in the streaming generator), and test it as far as possible without real sockets.

## Evidence (the report is rejected without it)
- A table mapping items 1–5 **and** the original mandatory tests A–F to test names, with the failing line before the fix (or "passed immediately") and the passing line.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api` and the backup module at least 1 % above their gates.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19i. **Parallel engineer M19j** (drill) is in `pipeline/`, `alerts/`, `recording/retention.py`, `api/routes/admin.py` (drill section) and migration 0009. It is landing first, so keep your `api/routes/admin.py` changes confined to the backup section. Moving the backup route into a new `api/routes/backup.py` is **preferred** (one router line in `api/app.py`).
