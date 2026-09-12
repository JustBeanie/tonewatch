# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it. Resolved history lives in `docs/pm/reviews.csv` and the commit log.

## Open

- **M8 (Docker) — HTTPS in the image.** The image's PyAV wheel must open **public** HTTPS with the product options (`tls_verify=1` + certifi `ca_file`). Linux wheels honour `ca_file` (CI run 34673148889), but the image may ship a different wheel. *In `docs/pm/briefs/M8.md`.*
- **M9 (Windows native).**
  - **MQTT selector thread:** `test_mqtt_real_broker_via_selector_thread` has an unconditional `@pytest.mark.skip`, so it runs on **no** platform, and the Windows selector-thread MQTT path has only a fake-client test. The M9 brief must require a real round-trip on windows-latest (amqtt in its own `SelectorEventLoop` thread, or a mosquitto binary) and remove the skip. The Linux real-broker test passes on ubuntu and ubuntu-arm.
  - **HTTPS:** Windows PyAV 18.1.0 does TLS through schannel, which **ignores `ca_file`** and uses the OS store. Public-CA feeds work. Document this.
  - **sounddevice / NumPy 2.5:** sounddevice 0.5.6 sets `ndarray.shape` in its cffi callback, which NumPy 2.5 deprecates. A future NumPy that removes the setter breaks the soundcard source at runtime. Re-verify on M9 and in the HIL checklist, and track the upstream fix.
- **M10 / M11 (HA consumers).** Alert payloads carry a **relative** `recording_url` (`/api/recordings/{id}`), which a webhook receiver, an HA entity attribute or a phone notification can't fetch.
  - Needs a `public_base_url` setting, or for the add-on the ingress URL / Supervisor-discovered host.
  - The M11 integration should resolve `media_content_id` through its authenticated proxy. Decide this in the M10 brief.
- **S5 — ASVS checklist integrity.**
  - **Brittle evidence:** evidence is cited as `path:line`, which breaks on every edit to a cited file. PM relocated `api/app.py` rows twice while landing S4 and W1b. Add an `evidence snippet` column that the validator locates (failing if absent or ambiguous), so `path:line` becomes derived.
  - **Hash guard:** add a test asserting the vendored ASVS CSV sha256 equals the pin in `docs/security/asvs/source/README.md`. The pre-commit global exclude already protects the bytes.
  - **Converting gaps:** 180 GAP rows need converting chapter by chapter on a gap-by-default rule. The PM reviews every positive row.
  - **Nits from S4-close:** V3.3.2 (SameSite) cites the CSRF check instead of the `set_cookie` samesite argument, and the V16.5.1 note carries an "applicability justified" phrase.
- **Later cleanup:** `types-pyyaml` is listed as a runtime dependency in `backend/pyproject.toml`; move it to dev dependencies.
- **Environment:**
  - The Codex sandbox user owns `.pytest-tmp/`, `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are gitignored and harmless, but only that user can delete them.
  - The sandbox has no schannel credentials, so engineer TLS/HTTPS probes, `git ls-remote` and `curl` fail inside it. Verify TLS on the PM host or CI.
- **Leftover dirs:** `C:\Users\beanie\Documents\Proj\tonewatch-m7`, `tonewatch-s4`, `tonewatch-hotfix` and `tonewatch-hotfix2` still hold sandbox-owned files. Their git registrations and branches are gone, so the user can delete the folders manually.

## Standing rules for every brief (now also in `AGENTS.md`)

- Engineers never edit `docs/pm/**`. W1a-fix4 rewrote this file mid-run. Check `git status -- docs/pm` at every review.
- Never replace ignore files; extend them. Never reformat vendored or upstream files. Never weaken a gate, whether skips, hand-edited lockfiles or a widened CSP.
- Integration tests wait for **persisted** state with a bounded timeout. Update platform-skipped (`skipif sys.platform`) tests touching changed code. Tests never open real devices.
- Every CI job has `timeout-minutes`, and pytest enforces a 120 s per-test timeout with faulthandler.
