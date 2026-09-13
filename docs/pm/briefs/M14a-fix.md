# Brief: M14a-fix — live restream review findings (new thread)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m14a`, which already contains the M14a implementation. Build on it. **E2E port:** `TONEWATCH_E2E_PORT=8804` (leave `TONEWATCH_E2E_URL` unset; in cmd, `set X= && …` sets it to a space).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M14a: FAIL (security gate weakened + two functional bugs)
**Keep:**
- the token design (`v1.<expiry>.<nonce>.<sig>`, dedicated secret, `compare_digest`, source scope, rotation)
- listener caps, the 404 when disabled, the URL issuance audit
- no encoder without listeners, the drop-oldest queues, the stalled-listener test, the two-listener decode test
- ADR 0011 with measurements

**Evidence rule:** every fix needs the red-first failure line of a new test, the passing line, and a short diff excerpt with file:line. A report that claims work without evidence is rejected. Never run `git add`/commit.

## 1. SECURITY: restore access logging; redact instead of disabling
- **What went wrong:** you set `"access_log": False` in `UVICORN_SECURITY_OPTIONS` and **edited `tests/unit/test_s4_security.py` to expect it**. That turns off the HTTP access log for every request to hide one query parameter, which weakens the S4 audit trail. Changing a security test to match is a gate weakening. The "token never in logs" test then passes trivially, because nothing is logged.
- **Fix:**
  - Revert the `access_log` option and the S4 test edit (the test must match `origin/main` exactly).
  - Keep uvicorn access logging on, and add a `logging.Filter` (or access-log formatter) on the `uvicorn.access` logger that **removes the query string from the request line for every request**, or at minimum replaces any `t=` value with `t=REDACTED`. Install it wherever uvicorn is started (`__main__.py`, `service.py`) and in the app's own request logging.
- **Test** (red-first): run a real request through uvicorn's access logger configuration, e.g. `uvicorn.Config` plus its `LOGGING_CONFIG`, or by emitting through the `uvicorn.access` logger with the same args uvicorn uses. Assert that (a) an access log line **is** emitted for `GET /api/sources/x/live.mp3?t=<token>`, (b) it contains the path, and (c) it does not contain the token. Also assert (d) the structlog request log doesn't contain it.

## 2. Lag disconnect is sticky, and removed listeners hang
- **Bug:** `LiveHub.feed` sets `listener._full_since` the first time a queue is full and **never clears it**. A listener that was briefly full and then caught up is still disconnected `max_lag_s` later.
- **Fix the first part:** reset `_full_since = None` whenever the queue has room.
- **Second problem:** when the hub removes a listener server-side (lag or config change), the HTTP generator in `routes/live.py` is left blocked on `await listener.get()` forever, because nothing wakes it.
- **Fix the second part:** closing a listener must wake its consumer (for example a sentinel `b""` or an `asyncio.Event` checked alongside `get()`). The generator then ends and the response completes.
- **Tests** (injected monotonic clock):
  - a listener full for less than `max_lag_s` that then drains stays connected past `max_lag_s`
  - a listener continuously full for more than `max_lag_s` is removed, **and its HTTP response body iterator finishes** within a bounded time
  - after a server-side removal, the listener count drops and the encoder is released if it was the last one

## 3. Player compatibility: Range and HEAD
- **Bug:** `live.mp3` returns **416 for any `Range` header**. Home Assistant media players, Cast receivers and Sonos commonly send `Range: bytes=0-` to live HTTP streams, so they would be refused. That defeats M14's goal of playing live audio in HA.
- **Fix:** ignore `Range` and always answer `200` with the live stream plus `Accept-Ranges: none`. Add `HEAD` support that returns the same headers (`Content-Type: audio/mpeg`, `Cache-Control: no-store`, `Accept-Ranges: none`) with auth/token checks, **without** adding a listener or starting an encoder.
- **Tests:** a GET with `Range: bytes=0-` gives 200 and valid MP3 bytes; HEAD with a valid token gives 200, headers, an empty body, and no listener change; HEAD with a bad token gives 401.

## 4. Secret file creation race
`read_or_create_live_secret` checks `is_file()`, then writes. Two concurrent first requests can write different secrets and invalidate the first token.
- **Fix:** create atomically (`os.open` with `O_CREAT | O_EXCL`, mode 0o600; on `FileExistsError`, read the file).
- **Test:** simulate a concurrent create (patch to force the race) and assert both callers get the same bytes.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- **Never weaken or edit existing security tests to match new behaviour.** Add new tests instead.
- No new `noqa`/`type: ignore` without a same-line justification. No new dependencies.
- Never `git add`, commit or push.

## Definition of done
- For each numbered item, the report shows red-first, passing and a diff excerpt.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty; paste the (empty) output.
- `just check` passes. Paste the pytest count before (413) and after, plus vitest.
- `just e2e` with port 8804 passes 4 specs (a teardown-only hang is acceptable if stated).
- `just ci-local` passes up to api-drift. If api-drift fails only on uncommitted generated files, paste `git diff --stat -- web/src/api`.
