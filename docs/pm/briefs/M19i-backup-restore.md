# Brief: M19i — M19.6 backup and restore (backend + API + CLI)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19i` (branch `m19i`). **E2E port:** `TONEWATCH_E2E_PORT=8848`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro and **M19.6** (~line 680).
- `storage/db.py`: `create_database`, `upgrade_database`, `checkpoint_database` and the Alembic head (`storage/migrations/versions/`, currently `0008`).
- `config/store.py` and `config/history.py`: config versions are secret-bearing files under `config-history/`.
- `api/auth.py`: the secret files in the data dir (`api_token`, `api_token_grace`, `ui_password`, `live_stream_secret`).
- `recording/retention.py`: `safe_recording_path`, and the orphan scanner's temp-file rules.
- `api/routes/maintenance.py`: the shared `maintenance_lock`.
- `__main__.py`: how CLI subcommands are structured.

## Required
1. **Archive format.** One `.tar.gz` (or `.zip`; pick one and document why) containing:
   - `manifest.json`: format version, ToneWatch version, Alembic revision, created-at, an `include_recordings` flag, and a list of every file with its size and SHA-256
   - `config.yaml`
   - `tonewatch.db`: a **consistent online copy** made with the SQLite backup API (`sqlite3.Connection.backup`) in a worker thread, never a raw file copy of a live WAL database
   - optionally `recordings/…`: relative paths only, with every file passed through `safe_recording_path`, no symlinks and no `.tmp`/dot files

   **Secrets:** the archive includes `config.yaml` (which holds target secrets) and the DB. Decide and document whether the auth secrets (`api_token`, `ui_password`, `live_stream_secret`) and `config-history/` are included.
   - **The default is to exclude them.** After a restore the token regenerates and the UI password must be set again. That keeps the archive less dangerous.
   - An explicit `include_credentials` option adds them.

   Write this down in `docs/guide/admin.md` together with an "archives contain secrets; store them like a password" warning.
2. **Create.**
   - `POST /api/admin/backup` with `{include_recordings: bool, include_credentials: bool}`:
     - uses `write_auth`; `include_credentials` is refused through ingress
     - is audited and rate-limited
     - holds the shared `maintenance_lock` (409 when busy)
     - streams the archive as a download with `Cache-Control: no-store`
     - builds it in a temp file in the data dir that is always cleaned up, with a size guard
   - CLI: `tonewatch backup create --out FILE [--include-recordings] [--include-credentials]` works on a stopped instance as well.
3. **Restore.** CLI first: `tonewatch backup restore FILE [--dry-run]`. Restoring into a running server is dangerous. Restore only runs while the app is stopped; the CLI refuses if the data dir's lock or port shows a running instance (document the check you use).
   - **Verify before touching anything:**
     - the format version is known
     - every manifest checksum matches, and no archive member is missing or unlisted
     - no member has an absolute path, a `..` segment, a symlink, a hard link or a device entry (**tar/zip slip**)
     - the total uncompressed size stays under a cap (**zip bomb**)
     - the Alembic revision is **not newer** than this build's head; a newer one is refused with a clear message
   - **Apply:**
     - extract to a staging dir inside the data dir
     - move the current data aside into `data/pre-restore-<timestamp>/` (never delete it)
     - swap in the staged files
     - run `upgrade_database` for an older revision
   - Any failure rolls back to the moved-aside data. `--dry-run` prints the manifest summary and the compatibility verdict and writes nothing.
   - **No HTTP restore endpoint in this slice.**
4. **Add-on note:** the HA add-on already has Supervisor backups. Document that this feature is for Docker and Windows users; it still works in the add-on.

## Mandatory tests (write first; show each failing line)
- **A. Consistency:**
  - a backup taken while another connection holds an open write transaction and WAL frames exist contains all committed rows and none of the uncommitted ones
  - restoring it gives a DB that passes `PRAGMA integrity_check`
- **B. Round trip:** config, DB rows and (with the flag) recordings come back byte-identical by checksum. Without `include_credentials`, the auth secret files are absent from the archive **and** from the restored dir, and the app regenerates a token on start.
- **C. Hostile archives are all refused, and the data dir is unchanged (checked by hashing the whole tree):**
  - a checksum mismatch
  - an extra member not in the manifest
  - a missing member
  - `../evil`
  - an absolute path
  - a symlink member
  - a hard-link member
  - an oversized member (a bomb within the cap)
  - an unknown format version
  - a newer Alembic revision
- **D. Rollback:** inject a failure mid-swap (monkeypatch). The data dir is restored to its original tree hash, and `pre-restore-*` exists.
- **E. API:**
  - no auth gives 401; a cookie without CSRF gives 403
  - ingress with `include_credentials` gives 403
  - maintenance busy gives 409
  - a second call inside the rate limit gives 429
  - `no-store` is set
  - it is audited, and the audit row has no secret
  - the temp file is gone after both success and a client disconnect (as far as testable)
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` fully green, with every `check_package_coverage.py` line at least 1 % above its gate. Then `just ci-local` up to `api-drift` (run `just gen-api`). `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.6 `[~] ... — PENDING-REVIEW`.
- No new dependencies (`tarfile`/`zipfile`/`sqlite3`). No subdirectory `conftest.py`. Never weaken a gate. No real data.
- Add a threat-model row with id **TM-050** (M19j takes TM-051).
- **Parallel engineer M19j** works in `pipeline/`, `sources/`, `dsp/generator.py` and a drill route. Don't touch those. Keep any `api/app.py` edit to one router registration.
