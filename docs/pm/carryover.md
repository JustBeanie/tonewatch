# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it.

- ~~M0.7 bootstrap script fixes~~ done 2026-09-10 (PM rewrite: idempotent, private default, ruleset with 0 approvals + admin PR bypass).
- **Environment:** the sandbox user owns `.pytest-tmp/` (repo root), `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are harmless and gitignored, but only the sandbox user can delete them.
- **Later cleanup:** `types-pyyaml` is listed as a runtime dependency in `backend/pyproject.toml`; move it to dev dependencies.
- **M8 brief:** the runtime image needs `libportaudio2`, because sounddevice wheels don't bundle it on Linux.
- **S4 (ASVS audit):** from the M5a review.
  - `test_secrets_never_logged` uses `structlog.testing.capture_logs`, which bypasses processors, so redaction of *rendered* output isn't directly asserted.
  - The chunked-upload (no Content-Length) byte-counting path in the analyze body guard has thin test evidence.
  - Re-verify both.

- **Watch Windows CI:** after the RtlSdrSource `communicate()` fix, confirm the flaky Windows `ResourceWarning: unclosed _ProactorReadPipeTransport` failure (run 34644998370) doesn't recur.
