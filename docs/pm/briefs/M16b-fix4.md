# Brief: M16b-fix4 — find where the test-trigger `ToneDetected` disappears in the e2e server (instrumented debugging)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-ec49-7183-af57-74f0736f51dd`; self-contained if resume fails) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16b`. **E2E port:** `TONEWATCH_E2E_PORT=8828`. The M16b rules apply.

## Where we are
- **Your frame log was right and the PM's client-batching theory was wrong.** Thank you for stopping and showing the evidence.
- **The PM reproduced the backend path in-process:** an ASGI app, a WebSocket subscribed to `events`, then `POST /api/tonesets/{id}/test` with a bearer token. Frames `ToneDetected` then `CallClosed` **both arrive, in order**. So bus fan-out, `_event_pump`, `serialize_event` and `ClientQueue` work in isolation.
- **So the loss is specific to the running e2e server:** a real supervisor and lifespan, a cookie session, CSRF, config hot-apply after the agency save, and multiple sockets per page.

## Hypotheses to test, in order
1. **The trigger didn't publish on the bus the WS pump reads.** Check `app.state.ws_hub` being reset (`api/app.py` sets `app.state.ws_hub = None` around line 220) during a lifespan or config apply, and whether a new hub or pump is created while the map socket stays attached to an old hub.
2. **The map socket was closed or replaced** (overflow close 1013, heartbeat close, or a reconnect) between `subscribed` and the trigger, so the frames went to a dead client.
3. **The trigger request hit something else:** the wrong tone set id (the fixture id may differ from `fixture-page`), a CSRF or 403 retried, or the response was 200 from a different route.
4. **The pump task died on an earlier event** (an exception in `serialize_event` for an event with a nested non-JSON value, e.g. a dict containing a datetime) and was never restarted. Later frames would then be missing for **all** new sockets. Check `app.state.ws_pump.done()` and its exception.

## Required
- **Temporary instrumentation only** (remove it all before reporting): structlog lines in the test trigger endpoint (published event types and bus id), in `_event_pump` (each event type received, the hub id, the client count), in `WebSocketHub.add` and remove, and in `ClientQueue.put` (dropped by topic filter or overflow). Also check whether `ws_pump` is done, with its exception.
- Run the e2e scenario and paste the **server log lines** around the trigger, showing exactly where `ToneDetected` stops.
- **Fix the real root cause** with a failing regression test at the right level (a backend integration test if it's the hub or pump, a Vitest test if it's the client). If hypothesis 4 is true, the pump must survive a bad event: log the type, skip it, keep running. Add a test that publishes an unserializable event followed by a normal one, and the normal one arrives.
- Then e2e test 7 passes, and all 7 specs pass.

## Evidence (the report is rejected without it)
- The server log excerpt that proves the root cause.
- The regression test's failing line and passing line.
- The full e2e per-test lines (7/7), `just check` green, and a note that the instrumentation was removed (`git diff` has no debug lines).
- **Honesty rule:** as always. If the root cause isn't found after instrumenting, report the logs and stop.
