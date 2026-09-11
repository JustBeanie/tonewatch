# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it.

- **M3.3 brief:** add a test that proves `EventBus.publish` from a non-async thread (the sounddevice callback) delivers through `call_soon_threadsafe`. `events.py` lines 89–92 are untested after M1.
- **M3/M4 brief:** `storage/db.py` has 0% coverage; exercise it when the pipeline writes calls.
- **M0.7 (before the user runs it):** fix `scripts/gh-bootstrap.sh`. It needs:
  - no `--license` on repo create
  - `git remote add origin`
  - rulesets instead of classic branch protection
  - no required approval for a solo owner
- **Environment:** the sandbox user owns `.pytest-tmp/` (repo root), `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are harmless and gitignored, but only the sandbox user can delete them.
