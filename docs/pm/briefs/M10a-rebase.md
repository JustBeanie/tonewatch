# Brief: M10a rebase onto main after M9 (conflict resolution only)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high
**Work dir:** worktree `tonewatch-m10a` (branch `m10a`). You resume the M10a thread you already worked in.

## Situation
Your M10a work (add-on mode) is still uncommitted in this worktree, based on `d3643d5`. Since then `main` gained:
- **S5 DAST fixes** in `api/app.py`, `api/routes/auth.py` and `api/spa.py`: login returns 422 on malformed bodies, the SPA CSP adds `form-action`/`base-uri`/`object-src`, and responses add Permissions-Policy/CORP/COOP/COEP headers. ASVS evidence lines moved accordingly.
- **The release workflow fix** and a **0.2.0 version bump**. `test_version.py` no longer hardcodes the version.
- **A looping `FileAudioSource` fix:** stream time no longer rewinds on a wrap, and pacing continues.
- **The CI diet** (workflows only) and `just ci-local`.
- **M9 (Windows native)**, which also changed four of your files: `backend/src/tonewatch/__main__.py` (service and selftest subcommands), `settings.py` (frozen `%PROGRAMDATA%` data dir), `alerts/mqtt.py` (bounded close timeouts on the selector-thread path), and `storage/db.py` (alembic.ini fallback for the frozen build).

The PM has already run `git stash push -u` → `git merge --ff-only origin/main` → `git stash pop` in this worktree. Any file with `<<<<<<<` markers is a conflict for you to resolve. A pre-rebase backup exists on the PM side, so never re-create your work from memory.

## Required
1. **Resolve every conflict marker, keeping BOTH sides' behaviour:**
   - **`__main__.py`:** M9's `service`/`selftest` subcommands **and** your `db checkpoint` subcommand.
   - **`settings.py`:** M9's frozen data-dir default **and** your add-on option mapping, `mqtt_mode`, `public_base_url` and the redaction behaviour. Don't reorder existing fields.
   - **`alerts/mqtt.py`:** M9's `CLIENT_CLOSE_TIMEOUT_S` bounded close **and** your Supervisor credential resolution and `source` handling.
   - **`storage/db.py`:** M9's `_internal/alembic.ini` fallback **and** your `checkpoint_database` + errors.
   - **Your `api/app.py` changes:** re-apply them onto main's DAST-fixed version, keeping all new security headers and the 422 login handling.
2. **ASVS:** re-derive `path:line` evidence for every positive row from its unique snippet (`docs/security/asvs/checklist.csv`, written QUOTE_ALL with LF), because both sides shifted lines. Don't change any row's status or snippet text except where your own code moved.
3. **Tests:** your tests and M9's must all pass together. Where a test of yours asserted an old CSP or header string, update it to main's current values. Never weaken an assertion.
4. **`docs/PROGRESS.md`:** keep main's lines (S5 `[x]`, the M13 section, M9 `[~]`) and your M10.2 `[~] PENDING-HIL`.

## Standing rules
- Never edit `docs/pm/**`. Never delete or overwrite changes from either side that you don't understand; ask in your final message instead.
- Never weaken a gate. Tests never open real devices or reach a real Supervisor.
- Don't commit, fetch or push; the PM does all git network operations and commits.

## Definition of done
- `git diff --check` is clean, and `rg -n "^(<<<<<<<|=======|>>>>>>>)" backend web docs scripts .github` finds nothing.
- `just ci-local` exits 0 with `TONEWATCH_E2E_PORT=8792`. Paste the tail.
- The final message lists each conflicted file and how you combined the two sides.
