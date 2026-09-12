# PM review: S4 fails. The checklist evidence is hollow, and the redirect SSRF is still open.

S4 did a lot of real, good work; keep all of it:
- the official ASVS 5.0.0 CSV, vendored (PM verified the sha256 against upstream)
- all 253 L1+L2 IDs with verbatim text
- the audit trail and 0003 migration
- ETag / `If-Match` config writes
- the resource caps and the bounded login throttle
- the stream scheme allowlist
- rendered-log redaction and the chunked-upload guard

Fix exactly the findings below. You are resuming in the `tonewatch-s4` worktree.

## 0. Your worktree was rebased by the PM (read this first)
- The PM moved your uncommitted S4 work onto `main` at `9ef8f0c`, which contains **W1a/W1a-fix**:
  - the recorder, watchdog and retention wiring
  - `RecordingStored`
  - tone-set hot reload
  - `create_app(sleep=…, source_factory=…, watchdog_no_data_s=…, shutdown_timeout_s=…)`
- Only `pipeline/supervisor.py` conflicted. The PM resolved it by **keeping both**: W1a's `recorder_hook` / `source_factory` / `watchdog` arguments **and** your `source_settings=self.settings`.
- **Verify that the production path is correct.** `Channel` uses `source_factory` when it's given; otherwise it uses `make_source(config, settings=source_settings)`. In production `source_factory` is `None`, so your stream settings must still reach `StreamAudioSource`.
- **Test:** `test_stream_block_private_setting_reaches_running_source`.
  1. Go through `create_app` lifespan with a `stream` source pointing at a private or loopback address, and `stream_block_private=True`.
  2. The running supervisor publishes `FeedHealthChanged(healthy=False)` with an unsafe-URL reason.
  3. No PyAV open is attempted (spy on `av.open`).

## 1. The redirect SSRF is NOT mitigated, and its test is hollow
- **Evidence.** The PM ran a real PyAV 18.1.0 probe against libavformat 62.12, using a local server that answers 302 to a second local server with a hit counter:
  - `options={"http_max_redirects": "0"}`: the redirect **is followed** (target hit +1, frames decoded). FFmpeg silently ignores unknown AVOptions.
  - `options={"max_redirects": "0"}`: `OSError: I/O error`, target hit +0.
- `test_stream_redirect_to_blocked_host_refused` only asserts a constant list and `_decode_url.__defaults__`. It proves nothing.
- **Don't simply block all redirects.** Real scanner feeds (Broadcastify and many Icecast relays) answer 302 to a relay host.
- **Required design:**
  1. Resolve redirects in Python **before** FFmpeg: `httpx` with `follow_redirects=False`, at most 5 hops.
  2. Validate **every** `Location` hop with `resolve_and_validate` (scheme allowlist + address policy).
  3. Hand FFmpeg the **final** validated URL with `max_redirects=0`, so FFmpeg can never follow a redirect you didn't validate.
  4. RTSP has no HTTP redirects; keep it as-is.
- **Tests.** All use real sockets and real PyAV. Mocks of `av.open` are not allowed for these three.
  - `test_ffmpeg_redirect_option_is_effective`: with the **exact** options dict `_decode_url` builds, a local 302 is not followed (target hit counter stays 0).
  - `test_stream_redirect_to_blocked_host_refused`: a 302 to a host your policy blocks gives `SourceConfigError` or `SourceUnavailable`, and the blocked target's hit counter stays 0. Use a monkeypatched policy that treats one loopback port as blocked and another as allowed. Document how.
  - `test_stream_redirect_to_allowed_host_followed_and_decoded`: a 302 to an allowed host decodes audio frames.

## 2. IP pinning breaks real streams and never re-resolves
- `StreamAudioSource.__aiter__` rewrites the URL host to the resolved IP and calls `_decode_url(str(safe_url))` **without** `resolved_host`. No `Host` header is sent, so name-based virtual hosts (CDNs, shared Icecast) get the IP as Host.
- For `https`, connecting to a bare IP breaks SNI and certificate hostname checks.
- `_resolved` is computed once in `open()` and reused across every reconnect, so a CDN IP rotation leaves the source stuck on a dead address.
- **Required:**
  - **Pinning.** Pick one option and write ADR `docs/decisions/0005-stream-url-pinning.md`:
    - **(a)** don't rewrite the host. Validate DNS immediately before **every** open, including reconnects and each redirect hop. Record the DNS-rebinding TOCTOU window as accepted risk `AR-003`, expiring in ≤90 days.
    - **(b)** keep pinning, but send the original `Host` header, keep SNI and hostname verification correct for https, and re-resolve on every reconnect.
  - **Probe TLS verification.** For `https`, determine whether this PyAV/FFmpeg build verifies certificates by default. If it doesn't, enable it (`tls_verify=1` plus a CA file, e.g. certifi) **only after proving with a real probe** that the option names take effect.
  - **If the build can't verify certificates,** say so, and record it as an accepted risk with the probe output as evidence.
- **Tests:**
  - `test_stream_sends_original_host_header`: a local server records the `Host` header. Connect via `http://localhost:<port>/`; the header must be `localhost:<port>`.
  - `test_stream_revalidates_dns_on_every_reconnect`: count `resolve_and_validate` calls across a forced reconnect. The count must be ≥2, and a second resolution to a blocked address stops the source.
  - `test_stream_https_certificate_verification`: a real local self-signed TLS server is refused when verification is on. If the build can't verify, write the test to document the actual behaviour, and link the AR.

## 3. Show the exploit is real, and the defence-in-depth control that stops it
`test_file_scheme_exploit_regression` only shows validation rejects `file:`. Add `test_ffmpeg_protocol_whitelist_blocks_file_read_even_if_validation_bypassed`:
1. Write a temp `api_token`.
2. Show that `av.open("file:///…/api_token")` **without** your options reads its bytes: the vector is real.
3. Show that `_decode_url` with URL validation monkeypatched away still refuses the same URL, because of `protocol_whitelist`.

## 4. The ASVS checklist evidence is hollow; redo it honestly
The PM counted **5 distinct tests and 5 distinct evidence lines** across the 210 `pass`/`fixed` rows:
- `test_security_headers_present` ×102, at `api/app.py:120`
- `test_rendered_log_output_redacts_secrets` ×70, at `routes/auth.py:45`

All rows carry the same boilerplate note. Examples:
- V6.4.3 (password reset) is marked `fixed` citing the log-redaction test, though ToneWatch has no password-reset flow.
- V2.3.3 (transactions) and V3.7.1 (client-side tech) cite the same test.

The `level` column also doesn't match the source's `L` value on any of the 253 rows.

The brief's hard "fail count = 0" rule pushed you toward this. That rule changes:
- **Statuses:** `pass`, `fixed`, `na`, `accepted`, **`gap`**.
  - A `gap` row references a `GAP-###` entry in `docs/security/gaps.md`, with the requirement, why it is unmet, and a **target milestone** (S5, S6, M9, M10, M11 or M12).
  - Honest gaps are acceptable. Fabricated passes are not.
- **`pass` / `fixed` rows:**
  - `evidence` = the path:line of the specific control that satisfies **this** requirement.
  - `test` = a test whose assertions exercise **that** control.
  - `notes` = one row-specific sentence on how the control meets the requirement.
  - `fixed` only when S4 changed code for this requirement; controls that already existed are `pass`.
- **Documentation or process requirements** (for example protection-level documentation) may use `test = doc-only` with `evidence` pointing into `docs/`, capped at 40 rows.
- **N/A rows** need a concrete reason.
- **`level`** must equal the source `L` exactly.
- **Strengthen `test_asvs_checklist.py`** to enforce all of it:
  - `level` equals the source `L`.
  - No test function is cited by more than **8** rows.
  - No `path:line` is cited by more than **8** rows.
  - Every note is ≥40 characters, and no note text appears in more than 2 rows.
  - `doc-only` rows are ≤40, with evidence under `docs/`.
  - `gap` rows reference an existing `GAP-###` with a target milestone.
  - `accepted` rows reference an `AR-###` whose expiry date parses, is in the future, and is ≤90 days out.
- **Report:** a per-chapter table with a `gap` column, plus the GAP list with targets.
- **The PM will sample 15 random rows by hand.** Any cited test that doesn't exercise the cited control fails the round.

## 5. Tests must never open real audio hardware
On the PM host (which has real audio devices), `backend/tests/integration/test_api.py::test_api_resources_and_rejections` configures a `soundcard` source, and the app opens a live PortAudio stream. sounddevice 0.5.6 sets `ndarray.shape` in its cffi callback, NumPy 2.5 deprecates that, and under `-W error` the test fails. You couldn't see this because the sandbox has no audio device.
- **Fix:**
  - Patch the soundcard source in that test.
  - Add an autouse conftest guard that makes `sounddevice.InputStream` / `RawInputStream` raise unless a test opts in with an explicit marker.
- **Test:** `test_tests_cannot_open_real_audio_devices`.

## Constraints
- Stay in `backend/`, `docs/` and `web/src/api` (generated only).
- No `pragma: no cover`, no `mark.skip`, no new unjustified `noqa` / `type: ignore`, and no lowered gates.
- Every security test for findings 1–3 must fail on the current tree first. Quote one failure line each in the report.

## Definition of done
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Then `just check` runs **last**; paste its unfiltered tail.
- The final message includes:
  - a **finding → fix (file:function) → test** table for findings 0–5
  - the ASVS per-chapter table with gaps, and the GAP list with targets
  - the ADR choice for finding 2 and the TLS probe result
  - the accepted-risk list with expiry dates
