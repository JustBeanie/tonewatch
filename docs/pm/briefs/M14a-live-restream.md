# Brief: M14a — live audio restream (backend: M14.1–M14.3, M14.6)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m14a` (branch `m14a`, based on `origin/main`). **E2E port:** `TONEWATCH_E2E_PORT=8804`.

## Goal
Implement `PLAN.md` M14.1–M14.3 and M14.6: a per-source live MP3 stream that a browser or any Home Assistant `media_player` can play through a short-lived signed URL. **UI (M14.4) and the ha-tonewatch parts (M14.5) are out of scope.** Two other engineers are working in parallel on M15a (squelch, which also touches `pipeline/channel.py`) and M16a (agencies). Keep edits to shared files (`config/models.py` `AppConfig`, `pipeline/channel.py`, the generated web client, `docs/PROGRESS.md`) small and additive.

## Required
1. **Spike first (AGENTS rule 7).** Before building on it, prove with a unit test that PyAV can encode float32 16 kHz mono frames **incrementally** to MP3 (resampled to 44.1 kHz, CBR), and that the concatenated packet bytes from successive encode calls decode back with PyAV. Put the finding in `docs/decisions/0011-live-stream-encoding.md`, including the actual per-frame latency the encoder adds.
2. **`streaming/live.py` `LiveHub` (test-first).**
   - `Channel` hands each normalized frame to the hub through one small, non-blocking call, for example `hub.feed(source_id, samples, gate_open=True)`. The gate parameter exists so M15 can pass squelch state later. When the gate is closed, the hub feeds zeros to the encoder, so the stream carries silence.
   - The encoder for a source starts on the first listener and stops (and is released) when the last one leaves. No listeners means no encoding, and this is asserted in a test.
   - **Per-listener isolation:** a bounded `asyncio.Queue` of about 2 s of encoded audio. When full, drop the oldest chunk. A listener that stays behind for longer than a configurable limit (default 10 s) is disconnected. `feed` must never await a listener; a test with a deliberately stalled listener asserts detection latency is unchanged.
   - Encoding must not block the event loop for long. If a benchmark shows encoding more than a few ms per 100 ms frame, run it in a thread executor with bounded backlog. Report the measured numbers.
3. **API.**
   - `POST /api/sources/{id}/live-url`: auth + CSRF, like other mutating routes. Returns `{url, expires_at}`; the URL is ingress-aware for the web UI, and there is an option to build it from `public_base_url` for external players. Emit an audit event (source id, expiry; never the token).
   - `GET /api/sources/{id}/live.mp3` accepts the normal API auth **or** `?t=<token>`:
     - **Token:** HMAC-SHA256 over `(scope "live", source id, expiry, random nonce)`, keyed by a dedicated secret file in the data dir. Create the secret on first use with owner-only permissions, matching how the API token file is created. Never reuse the API token as the key.
     - Constant-time comparison, scoped to exactly one source, expiry enforced at connect.
     - Malformed, tampered, expired or wrong-source tokens are rejected with 401/403 and no detail that helps forgery.
     - The query string (the token) must never appear in logs, including uvicorn access logs and structlog request logging. Add a test that captures logs.
   - Response: chunked `audio/mpeg`, `Cache-Control: no-store`, no Range support, and correct handling of client disconnect (listener removed, encoder stopped if last).
   - **Caps:** `max_listeners_per_source` (default 4) and `max_listeners_total` (default 12). Over the cap returns 503. Listener counts appear in the source status in the API and in a WS event when they change.
   - Disabled globally or for that source returns 404 for both endpoints.
   - Regenerate the web client (`just gen-api`).
4. **Settings.** In `AppConfig`, add `live_stream: LiveStreamConfig` with `enabled` (default **false**), `bitrate_kbps` (32–128, default 48), the caps, `token_ttl_s` (60–86400, default 3600) and `max_lag_s`. Add per-source `live_stream_enabled: bool = True` on `SourceBase`. Changes hot-apply like other config.
5. **Security docs (M14.6).**
   - Add threat-model entries for: signed-URL leakage (player and proxy logs, HA history), listener-exhaustion DoS, token scope and replay within TTL, and the secret file.
   - Add ASVS checklist rows for the new endpoints, following the existing file conventions exactly (quoting, LF, line anchors).
   - Add a public docs page "Listen live" covering enabling, URLs, HA playback with `media_player.play_media` using a URL from the API, and the rebroadcast-regulation disclaimer.
6. **Tests.**
   - An integration test: a file source with 2 concurrent listeners, each decoding at least 2 s of valid MP3 via PyAV.
   - The stalled-listener latency test.
   - Token tests: expired, tampered, wrong source, missing, and a replay after the secret file is rotated.
   - Caps returning 503, the 404 cases, the log-redaction test, and no encoder with zero listeners.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate: no skips, no lowered coverage, no widened CSP, no `# type: ignore`/`noqa` without a same-line justification.
- Never print, log or commit anything from `backend/tests/fixtures/private/`.
- No legacy product naming (the clean-room pre-commit hook enforces it).
- Never commit or push. Don't bump unrelated pins; if you need a new dependency, stop and explain why in the report instead.

## Definition of done
- `just check` passes. Paste the pytest and vitest summary lines.
- `just ci-local` with `TONEWATCH_E2E_PORT=8804` passes, including security (semgrep, zizmor), api-drift and e2e. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- In `docs/PROGRESS.md`, M14.1–M14.3 and M14.6 are marked `[~] PENDING-REVIEW`, one line each.
- The final report lists every changed file, the ADR finding, the encoder CPU and latency numbers, the exact token format and verification code path, and the log-redaction proof.
