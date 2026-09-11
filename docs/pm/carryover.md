# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it.

- **M3.3 brief:** add a test that proves `EventBus.publish` from a non-async thread (the sounddevice callback) delivers through `call_soon_threadsafe`. `events.py` lines 89–92 are untested after M1.
- **M3/M4 brief:** `storage/db.py` has 0% coverage; exercise it when the pipeline writes calls.
- ~~M0.7 bootstrap script fixes~~ done 2026-09-10 (PM rewrite: idempotent, private default, ruleset with 0 approvals + admin PR bypass).
- **Environment:** the sandbox user owns `.pytest-tmp/` (repo root), `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are harmless and gitignored, but only the sandbox user can delete them.
- **S2 brief:**
  - Triage the 7 open Dependabot alerts. They are transitive web dev dependencies: js-yaml (3 high, 2 medium) and markdown-it (2 medium), all DoS or prototype pollution. Fix with `pnpm.overrides` or upgrades.
  - Dependabot security-update jobs fail because its pnpm 11.17 resolves against our pnpm 10 lockfile. Decide between Renovate-only and a `.github/dependabot.yml` that is compatible.
  - Pinned `actions/checkout`, `setup-node` and `pnpm/action-setup` target the deprecated Node 20 runtime. Bump them to current major versions, SHA-pinned.
- **M8 brief:** the runtime image needs `libportaudio2`, because sounddevice wheels don't bundle it on Linux.
