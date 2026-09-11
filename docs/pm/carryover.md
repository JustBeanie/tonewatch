# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it.

- **M3/M4 brief:** `storage/db.py` has 0% coverage; exercise it when the pipeline writes calls.
- ~~M0.7 bootstrap script fixes~~ done 2026-09-10 (PM rewrite: idempotent, private default, ruleset with 0 approvals + admin PR bypass).
- **Environment:** the sandbox user owns `.pytest-tmp/` (repo root), `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are harmless and gitignored, but only the sandbox user can delete them.
- **Later cleanup:** `types-pyyaml` is listed as a runtime dependency in `backend/pyproject.toml`; move it to dev dependencies.
- **M8 brief:** the runtime image needs `libportaudio2`, because sounddevice wheels don't bundle it on Linux.
