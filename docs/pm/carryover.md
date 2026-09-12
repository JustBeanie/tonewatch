# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it.

- ~~M0.7 bootstrap script fixes~~ done 2026-09-10 (PM rewrite: idempotent, private default, ruleset with 0 approvals + admin PR bypass).
- **Environment:** the sandbox user owns `.pytest-tmp/` (repo root), `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are harmless and gitignored, but only the sandbox user can delete them.
- **Later cleanup:** `types-pyyaml` is listed as a runtime dependency in `backend/pyproject.toml`; move it to dev dependencies.
- **S4 (ASVS audit):** from the M5a review.
  - `test_secrets_never_logged` uses `structlog.testing.capture_logs`, which bypasses processors, so redaction of *rendered* output isn't directly asserted.
  - The chunked-upload (no Content-Length) byte-counting path in the analyze body guard has thin test evidence.
  - Re-verify both.

- **Watch Windows CI:** after the RtlSdrSource `communicate()` fix, confirm the flaky Windows `ResourceWarning: unclosed _ProactorReadPipeTransport` failure (run 34644998370) doesn't recur. — run 34650516071 test-python windows-latest PASSED (1 of N). M6a run: Windows PASSED (2 of N); api-client-drift PASSED.

- **S4 priority, from the S3 review:**
  - TM-027: stream URL SSRF.
  - PM addition: PyAV/FFmpeg `av.open(url)` also honours FFmpeg protocols (`file:`, `concat:`, `subfile:`, `data:`, `pipe:`), so a stream source could read local files (for example `/data/api_token`) or chain protocols.
  - Needs a scheme allowlist (http, https, rtsp, rtsps, icecast), an FFmpeg `protocol_whitelist` option on open, re-validation on redirects, and blocked loopback/link-local/metadata addresses. Private RFC1918 LAN streams stay allowed by default, because a local Icecast server is a legitimate use.

- ~~M7 review watch-list~~ resolved by M7-fix (0002 migration, real amqtt broker test, Windows selector-loop thread). **Still PENDING Linux CI:** `test_mqtt_real_broker_call_health_lwt_and_discovery` must run (not skip) on ubuntu and ubuntu-arm after the merge push.
- **Merge `m7-alerts`:** the worktree pre-commit fails reproducibly on prettier/eslint (`Cannot find module ...\pnpm\bin\pnpm.cjs`) even with no engineer running, while the same shim works in main. That's environmental, so run the full gates in the main tree after the merge.
- **W1a (composition-root wiring), found by PM in the M6b-fix review.** Units are tested in isolation but never assembled in the running app:
  - The supervisor builds `Channel` with no `recorder_hook`, so `CallRecorder` is never instantiated in `src` and the app never records.
  - The `Watchdog` is created but not passed to the channel, so `on_frame` is never called.
  - `app.py` passes no `retention_service`.
  - An open recording isn't finalized on source EOF.
  - `channel.py` has an `except TypeError` hook-signature shim that swallows real errors.
  - Brief: `docs/pm/briefs/W1a.md`.
- **W1b (SPA serving + real e2e, M6.9 redo):**
  - Pull M8 required item 1 (the backend serves the SPA) forward into W1b, then drop it from `M8.md`.
  - The rejected harness is saved in the PM scratchpad and must NOT be reused as-is: it rewrote responses, faked a recording, rewrote WS Origin and injected `<base>`.
  - The `<base href="/">` injection suggests `base: './'` breaks asset loading on deep-link reloads such as `/tonesets/new`. W1b needs a `deep link reload renders` e2e test that works under an ingress-style prefix.
