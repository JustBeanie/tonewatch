# Brief: M18a-fix2 — Meshtastic: coalescing edge cases and the mandatory tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1c3-42b9-7691-ab5a-f764e7d4bf78`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18a`. **E2E port:** `TONEWATCH_E2E_PORT=8806` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M18a-fix: FAIL (edge-case bugs + tests)
**PM verified and kept:**
- The fake `sleep(0.01)` is gone.
- Coalescing runs as a task per `(call, target)` with an injected `sleep`.
- `coalesce_s` (0–15) and `timezone` (validated with `ZoneInfo`, then `TZ`, then UTC) are in place.
- The URL regex is broadened, with parametrized cases.
- Tone-set names resolve from config.
- The agency dict renders as names.
- The truncation property is now correct.
- `test_target` makes one attempt with no `AlertAttempt` row, and the route writes an `alert_target_test` audit event.

**Why it fails:** 7 tests added (413 → 420) against about 15 mandatory, plus these bugs:

## Bugs
1. **A removed target crashes the coalescing task.** `_coalesce_and_dispatch` uses `next(...)` without a default, and the target is looked up **before** the sleep but never re-checked after it.
   - If `reload` removes the target mid-window, the task must exit cleanly and send nothing. If the template changed, send the **new** template.
   - `reload()` and `stop()` must cancel pending coalescing tasks for removed targets, or for all targets on `stop()`, and await them without errors or warnings.
2. **Follow-up race.** `_mesh_sent.add(key)` runs **after** `await self._dispatch(...)`. A tone set that arrives while the first send is in flight still finds `key in self._coalescing`. It is merged into state but never sent, so it is silently lost.
   - **Fix:** mark the call as sent, or snapshot the tone-set list, **before** awaiting the send. Anything not in the snapshot goes out as one follow-up.
   - **Test** with a sender that blocks on an event.
3. **The follow-up must respect the limiter.** Verify what `force=True` bypasses. A follow-up for an already-sent call must still go through `min_interval_s`/`max_per_hour`, and a drop records exactly one `AlertAttempt` with error `rate_limited` and no retries. Fix it if `force` skips the limiter.
4. **Unbounded state.** `_mesh_sent` (and `_calls` entries a Meshtastic target relies on) must be pruned when the call closes, or be bounded. Add a test that 1,000 closed calls leave `_mesh_sent` empty or bounded.
5. **Test timeout.** `test_target` bounds the attempt with the dispatcher-wide `self.timeout_s`. Use the **target's own timeout** when it has one, as the M18a-fix brief required.
   - **Also:** the route test asserts a `call_id` in the response, but the contract is `{ok, error}`. Make the route and its test match the contract.

## Tests still required (mandatory; the report must map each test name to its item number)
6. **Coalescing timing** with an injected sleep/clock:
   - 1 s apart → one message naming both, which your test covers.
   - 5 s apart (after the window) → two messages when the limiter allows.
   - The limiter drops the second → one message plus one recorded `rate_limited` attempt.
7. **Embedded broker, end to end:** use the **existing** MQTT broker fixture from `tests/integration/test_mqtt_broker.py`; don't write a new broker.
   - Drive `AlertDispatcher.handle(ToneDetected(...))`, not the sender directly.
   - Subscribe and assert topic `msh/US/2/json/mqtt/`, QoS 1, retain false, and the exact JSON envelope.
8. **Rate limiting through the dispatcher:** `min_interval_s` and `max_per_hour` each yield exactly one `AlertAttempt` row with error `rate_limited`. Use a real session factory on a temp SQLite DB.
9. **Phases:**
   - `phases=["pre_alert"]` sends nothing for `recording_ready`/`closed`.
   - `phases=["recording_ready"]` sends only on that phase, **not coalesced** (coalescing applies to `pre_alert` only; assert no delay).
10. **Reload:**
    - A template change takes effect on the next call.
    - Removing a target mid-window cancels its task, with no send and no exception (bug 1).
11. **Timezone:** a fixed UTC instant renders in `America/New_York` with the correct local `HH:MM`. With `timezone` unset, `TZ=Europe/Berlin` via monkeypatch is honoured; with neither set, UTC.
12. **Agency rendering:** agency dict present, agency absent, `agency=None`, and a stacked call spanning two agencies. None of them renders `{`, `[` or `'id'`.
13. **`test_target` through the real `AlertDispatcher`** with a fake sender:
    - exactly one send, zero `AlertAttempt` rows (real temp DB), one audit row `alert_target_test` with `ok`
    - a failing sender's error surfaced in the response
    - a slow sender times out at the target timeout
14. **Secrets:**
    - `GET /api/alert-targets` and `GET /api/alert-targets/{id}` return the Meshtastic `password` masked, never plaintext.
    - The audit before/after diff for a create and an update doesn't contain the plaintext password.
15. **URLs in the payload:** a dispatcher payload with `recording_url` and a live URL (including a query token) produces a message containing neither.

## Evidence (the report is rejected without this)
- A table: test name → item number (1–15).
- For each bug (1–5), the red-first failing line, the passing line, and a diff excerpt with file:line. For tests that pass immediately against code already fixed, say so explicitly.
- The pytest count before (420) and after, the vitest line, and `just check`, `just e2e` and `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- No new dependencies, and none of the GPL `meshtastic` package or its protobufs.
- Invented node ids and names only.
- Never `git add`, commit or push. Don't describe work you haven't done.
