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
- **M9 (Windows native), found in the PM CI review of `37e7f42`.** `test_mqtt_real_broker_via_selector_thread` has an unconditional `@pytest.mark.skip`, so it runs on **no** platform, and the M7-fix "PENDING-CI" wording was misleading. The Windows selector-thread MQTT path has only a fake-client test.
  - The M9 brief must require a real round-trip on the windows-latest runner: amqtt started inside its own `SelectorEventLoop` thread, or a mosquitto binary.
  - Remove the unconditional skip.
  - The real Linux broker test PASSED on ubuntu-latest and ubuntu-24.04-arm (CI run 34661384428).
- **Leftover dir:** `C:\Users\beanie\Documents\Proj\tonewatch-m7` still holds files the sandbox user owns (`.tools`, `backend`, and others). Its git registration is pruned and `m7-alerts` is deleted, so the user can delete the folder manually.
- ~~Merge `m7-alerts`~~ done 2026-09-11 as squash `37e7f42`. The worktree pre-commit failed reproducibly on prettier/eslint (`Cannot find module ...\pnpm\bin\pnpm.cjs`) even with no engineer running, while the same shim works in main. That's environmental, so run the full gates in the main tree after the merge.
- **W1a (composition-root wiring), found by PM in the M6b-fix review.** Units are tested in isolation but never assembled in the running app:
  - The supervisor builds `Channel` with no `recorder_hook`, so `CallRecorder` is never instantiated in `src` and the app never records.
  - The `Watchdog` is created but not passed to the channel, so `on_frame` is never called.
  - `app.py` passes no `retention_service`.
  - An open recording isn't finalized on source EOF.
  - `channel.py` has an `except TypeError` hook-signature shim that swallows real errors.
  - Brief: `docs/pm/briefs/W1a.md`.
- **Test hermeticity + sounddevice / NumPy 2.5, found in the S4 review on 2026-09-11:**
  - `backend/tests/integration/test_api.py::test_api_resources_and_rejections` configures a `soundcard` source, so on a host with real audio hardware the app opens a PortAudio stream.
  - sounddevice 0.5.6 sets `ndarray.shape` inside its cffi callback. NumPy 2.5 deprecates that, and under `-W error` it surfaces as `PytestUnraisableExceptionWarning`, which fails intermittently on the PM host. CI runners and the Codex sandbox have no audio device, so they never see it.
  - **Fix (S4-fix):** tests must never open real devices. Patch the soundcard source factory in that test and add a conftest guard that fails any test importing a live `sounddevice.InputStream`.
  - **Production:** track the upstream sounddevice fix. A future NumPy that removes the shape setter would break the soundcard source at runtime, so M9 (Windows native) and the HIL checklist must re-verify it.
- **M10/M11 (HA consumers), from the W1a review:**
  - Alert payloads carry a **relative** `recording_url` (`/api/recordings/{id}`), which a webhook receiver, MQTT/HA entity attribute or phone notification can't fetch.
  - Needs a `public_base_url` setting, or for the add-on the ingress URL / Supervisor-discovered host.
  - The M11 integration should resolve `media_content_id` through its authenticated proxy rather than trusting the raw URL. Decide this in the M10 brief.
- **W1b (SPA serving + real e2e, M6.9 redo):**
  - Pull M8 required item 1 (the backend serves the SPA) forward into W1b, then drop it from `M8.md`.
  - The rejected harness is saved in the PM scratchpad and must NOT be reused as-is: it rewrote responses, faked a recording, rewrote WS Origin and injected `<base>`.
  - The `<base href="/">` injection suggests `base: './'` breaks asset loading on deep-link reloads such as `/tonesets/new`. W1b needs a `deep link reload renders` e2e test that works under an ingress-style prefix.
