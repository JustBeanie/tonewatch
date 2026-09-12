# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it. Resolved history lives in `docs/pm/reviews.csv` and the commit log.

## Open

- 🛑 **USER DECISION: release-please can't open PRs.** Since `d05564e`, `release.yml / release-please` fails with "GitHub Actions is not permitted to create or approve pull requests". Before failing, it pushed branch `release-please--branches--main`.
  - **Option 1:** enable *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests*.
  - **Option 2:** give that job a fine-grained PAT secret with `contents` + `pull-requests` write.
  - This is a repository setting, so it needs the user's explicit OK. Until then that job stays red, and it doesn't block other work.

- **Image size margin is only about 2.8 MB** (CI run 34681525844, `e57ec0d`): 347,219,215 bytes against the 350 MB budget, after trimming venv tests, `__pycache__` and numpy headers in the builder stage.
  - The next runtime dependency will probably break the `size` job.
  - **Next lever, in the builder stage only:** `strip --strip-unneeded` on the `.so` files in site-packages (`av.libs`, `numpy.libs`), with the in-image import smoke as a guard. Deleting files in the runtime stage cannot shrink lower layers.
  - Put this in the S5, M9 or M10 brief, whichever adds dependencies first.
- ~~**M8 (Docker) — HTTPS in the image.**~~ Resolved: smoke verifies PyAV TLS against github.com inside the image (CI run 34681525844). History: The image's PyAV wheel must open **public** HTTPS with the product options (`tls_verify=1` + certifi `ca_file`). Linux wheels honour `ca_file` (CI run 34673148889), but the image may ship a different wheel. *In `docs/pm/briefs/M8.md`.*
- **M9 (Windows native).**
  - **MQTT selector thread:** `test_mqtt_real_broker_via_selector_thread` has an unconditional `@pytest.mark.skip`, so it runs on **no** platform, and the Windows selector-thread MQTT path has only a fake-client test. The M9 brief must require a real round-trip on windows-latest (amqtt in its own `SelectorEventLoop` thread, or a mosquitto binary) and remove the skip. The Linux real-broker test passes on ubuntu and ubuntu-arm.
  - **HTTPS:** Windows PyAV 18.1.0 does TLS through schannel, which **ignores `ca_file`** and uses the OS store. Public-CA feeds work. Document this.
  - **sounddevice / NumPy 2.5:** sounddevice 0.5.6 sets `ndarray.shape` in its cffi callback, which NumPy 2.5 deprecates. A future NumPy that removes the setter breaks the soundcard source at runtime. Re-verify on M9 and in the HIL checklist, and track the upstream fix.
- **M10 / M11 (HA consumers).** Alert payloads carry a **relative** `recording_url` (`/api/recordings/{id}`), which a webhook receiver, an HA entity attribute or a phone notification can't fetch.
  - Needs a `public_base_url` setting, or for the add-on the ingress URL / Supervisor-discovered host.
  - The M11 integration should resolve `media_content_id` through its authenticated proxy. Decide this in the M10 brief.
- **S6/S7 — remaining ASVS GAP rows.** S5 converted V3/V4 only, so 178 GAP rows remain. Convert them chapter by chapter on the gap-by-default rule; the PM reviews every positive row. Every positive row must carry a snippet that *proves* the control (S5 shipped a V3.4.2 snippet that was just a closing paren), and `fixed` means code changed in that milestone, otherwise use `pass`.
- **S5 follow-up — DAST tuning (watch the first CI run).** `zap-baseline.py` exits 2 on any WARN, including informational alerts, and the job requires exit 0. If the first run is red with exit 2, read the uploaded `zap-dast-reports` and add each real false positive to `docker/zap/rules.tsv` as `IGNORE` with a one-line justification. Never use `-I`, and fix every genuine finding in code.
- **Pin updates must never downgrade.** When re-pinning a floating `@vN` tag, pin the newest `vN.x.y` commit (S5 silently moved codeql-action 3.38.0 → 3.28.18 and setup-uv 6.8.0 → 6.4.3). The pin checker only runs online on the PM host and in CI (`security.yml / action-pins`); the sandbox run skips it.
- **Nit:** `storage/migrations/env.py` catches `AttributeError` as well as the context proxy's `NameError`; narrow it.
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
