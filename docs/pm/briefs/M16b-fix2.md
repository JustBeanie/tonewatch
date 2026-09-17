# Brief: M16b-fix2 — minimum pulse duration (PM-authorized), then finish the e2e

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-ec49-7183-af57-74f0736f51dd`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16b`. **E2E port:** `TONEWATCH_E2E_PORT=8828`. The same rules as M16b and M16b-fix apply.

## PM decision on your blocker
Your analysis is right: `POST /api/tonesets/{id}/test` publishes `ToneDetected` and `CallClosed` back to back, so the pulse is never observable. In production that's also bad UX: a short page (or a test page) would pulse for zero frames.

**Authorized product change (UI only, no backend change):**
- An agency marker's pulse lasts **at least 8 seconds** from the call-start event.
- A `CallClosed` arriving before then ends the pulse at the 8 s mark.
- A `CallClosed` arriving later ends it immediately, as today.
- Put the duration in one exported constant.
- Implement it with a per-agency timer that's cleaned up on unmount, and handle overlapping calls for the same agency: the pulse ends when the **last** active call has closed **and** its minimum has elapsed.

## Required
1. Implement the minimum pulse in the map page or hook.
2. **Vitest with fake timers:**
   - start then close at +1 s: still pulsing at +7.9 s, not pulsing at +8.1 s
   - start then close at +20 s: not pulsing at +20.1 s
   - two overlapping calls on one agency: the pulse stays until both rules are satisfied
   - unmount clears the timers (no act warnings or leaks)

   Show each failing first.
3. **E2E test 7 (make it deterministic):**
   - Open `/map` **before** triggering.
   - Trigger via the CSRF-safe test path you added.
   - Assert the marker gets `marker-pulse` within 5 s.
   - Assert the call detail shows the agency.
   - Assert no external requests.
   - Link the tone set unconditionally.
4. **Keep your M16b-fix changes:**
   - the per-tone-set updates instead of the full-config PUT
   - readable 422 errors
   - inline checkboxes

## Noted, but not yours to fix
- Your capture exposed a backend bug: `GET /api/config` masks `live_stream.token_ttl_s` as `"[REDACTED]"`, because `is_secret_key` matches any key *containing* `token`. That breaks full-config round-trips.
- The PM will fix it in a separate brief. **Don't change `api/audit.py`**, since another engineer is working in adjacent code.

## Evidence (the report is rejected without it)
- The Vitest failing and passing lines for step 2.
- **The full e2e spec file on port 8828: all 7 tests passing, pasted** (per-test lines are enough if the launcher hangs after they print).
- `just check` green, with the Vitest count and web coverage.
- **Honesty rule:** as before.
