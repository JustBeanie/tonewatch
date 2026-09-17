# Brief: M16b-fix3 — root cause of the missing pulse is client-side event loss in `useSubscription`

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-ec49-7183-af57-74f0736f51dd`; self-contained if resume fails) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16b`. **E2E port:** `TONEWATCH_E2E_PORT=8828`. All M16b, M16b-fix and M16b-fix2 rules apply.

## PM diagnosis
Your M16b-fix2 report said no `ToneDetected` frame reaches the WebSocket after the trigger. The PM traced the code, and the likelier cause is on the client.
- **What the hook does:** `web/src/lib/ws.ts` `useSubscription(topic)` stores **only the latest message** in React state: `socket.onMessage(setMessage)`.
- **What happens on a test page:** `POST /api/tonesets/{id}/test` publishes `ToneDetected` then `CallClosed` back to back. Both frames arrive in the same tick, and React batches the two `setMessage` calls.
- **The result:** `MapPage`'s effect on `event` only ever sees `CallClosed`, and the pulse never starts.
- **What the backend does:** it delivers both. `api/routes/ws.py` `_event_pump` forwards every bus event except `ToneCandidateObserved`, and `test_ws_event_delivered_with_iso_fields` proves `ToneDetected` delivery.
- **Wider impact:** this is a **production bug beyond the map**. `Dashboard.tsx` and `DiscoveredTones.tsx` use the same hook and can silently drop events that arrive close together (a stacked page, detection plus close).

**Verify before you fix:** in the e2e, log **every** `framereceived` payload type on **all** page WebSockets (not only after `mapOpen`), trigger, and paste the frame types you see. If `ToneDetected` really is absent at the frame level, stop and report that evidence; otherwise continue.

## Required
1. **Add a lossless per-message API** in `web/src/lib/ws.ts`, e.g. `useWsEvents(topic, handler)`, which calls `handler(message)` for **every** message, in order, with the handler kept in a ref so re-renders don't resubscribe.
   - Keep `useSubscription` for the telemetry uses where "latest value" is correct (levels, spectrum), or reimplement it on the new API.
   - **Every** consumer that reacts to discrete events must use the lossless API: `MapPage`, `Dashboard`'s call feed and `DiscoveredTones`. Audit `web/src` for others and list them.
2. **`MapPage`:** process `ToneDetected` and `CallClosed` through the handler, keeping the 8 s minimum pulse logic.
3. **Dashboard and DiscoveredTones:** make sure no event is dropped. Keep their behaviour otherwise identical.

## Mandatory tests (write first; show each failing)
- **Hook test:** a fake socket emits two messages synchronously in one tick, and the handler is called twice, in order. This must **fail** against `useSubscription`-style state.
- **MapPage:** `ToneDetected` and `CallClosed` delivered in the same tick still pulse (fake timers: pulsing at +7.9 s, not at +8.1 s).
- **Dashboard:** two call events in one tick both appear in the feed.
- **E2E test 7** passes. Paste the full 7-test run on port 8828.

## Evidence (the report is rejected without it)
- The frame-type log from the verification step.
- The failing and passing lines for each new test.
- The full e2e per-test lines (7/7), and `just check` green (Vitest count and coverage).
- **Honesty rule:** as always.
