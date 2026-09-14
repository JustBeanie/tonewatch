# Brief: M18a-fix — Meshtastic review findings (new thread)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18a`, which already contains the M18a implementation. Build on it. **E2E port:** `TONEWATCH_E2E_PORT=8806`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M18a: FAIL (spec: fake coalescing, integration bugs, thin tests)
**Keep:**
- ADR 0012 (well sourced)
- `MeshtasticTarget` validation: node ids, exactly-one broker, channel-0 acknowledgement, placeholder allowlist
- UTF-8 truncation, QoS 1 / not retained, the per-target limiter, no new dependencies

**Evidence rule:** every fix needs the red-first failure line of a new test, the passing line, and a short diff excerpt with file:line. A report that claims work without evidence is rejected. Never run `git add`/`commit`.

## Bugs
1. **Coalescing is fake.** The dispatcher adds `await asyncio.sleep(0.01)` when a Meshtastic target exists. A stacked tone set arriving seconds later either sends a second message or is dropped as `rate_limited`. Remove the sleep.
   - **Implement real per-call coalescing in the Meshtastic path:** add `coalesce_s: float = 3.0` (0–15) on `MeshtasticTarget`. The first `pre_alert` for a call starts a timer. Tone sets for the same call that arrive before it fires are merged. One message goes out, listing every tone set/agency.
   - **A later tone set** for an already-sent call sends at most one follow-up, subject to the rate limiter. When the limiter drops it, that is recorded, never silently lost.
   - The coalescing timer must not block the dispatcher loop or other targets (use a task per call; cancel cleanly on `stop()`/`reload()`).
   - **Tests** (with an injected clock/sleep): two tone sets 1 s apart give one message naming both; 5 s apart give two messages when the limiter allows; the limiter dropping the second gives one message plus a recorded `rate_limited` attempt; other target types are not delayed.
2. **Tone-set ids instead of names, and agency dicts.**
   - The dispatcher state holds tone-set **ids**, so messages read `county-fire`. Resolve names from the current config.
   - When M16 lands, `payload["agency"]` will be a dict `{id, name, short_name, kind, lat, lon}`. The current `payload.get("agency")` would render its `str(dict)`.
   - **Fix:** `{agency_short}` and `{agency}` come from `agency["short_name"]`/`agency["name"]` when `agency` is a dict; otherwise fall back to tone-set names. Never render a dict or list repr.
   - **Tests:** agency dict present, agency absent, agency `None`, and a stacked call with two agencies.
3. **URL scrubbing misses most URLs.** `_URL` only matches `.com/.org/.net/.io/.dev`.
   - **Fix:** scrub any `scheme://…`, any host-like `label(.label)+` with an alphabetic TLD of 2+ chars (optionally with `:port`/path), IPv4 and bracketed IPv6 with optional port/path, and `www.`.
   - **Tests** (each must not survive): `https://home.example.zip/x`, `10.1.0.5:8080/api/recordings/1.mp3`, `[fe80::1]:8099/a`, `ftp://files.example/a`, `tonewatch.local/api`. Also make sure recording and live URLs present anywhere in the dispatcher payload never reach the message.
4. **Host timezone.** `render_message` formats `{time}` in the process's local zone; containers run UTC, so pages show the wrong time.
   - **Fix:** add `timezone: str | None` (an IANA name validated with `zoneinfo`) on `MeshtasticTarget`. When unset, use the `TZ` environment variable, falling back to UTC. Document it.
   - **Test** with a fixed UTC instant and `America/New_York`.
5. **The test endpoint writes orphan rows and retries.** `test_target` makes a random call id, runs the full 5-try `_dispatch` with backoff, and records `AlertAttempt` rows for a call that doesn't exist. `alert_attempts.call_id` is a foreign key to `calls`; SQLite doesn't enforce it, so the rows are silent orphans. It also records no audit event, unlike the existing tone-set test endpoint.
   - **Fix:** one attempt, no retries, no `AlertAttempt` row. Return `{ok, error}` from the single attempt in the response, and record an audit event `alert_target_test` (target id, ok; never secrets). Bound the request by the target's own timeout.
   - **Test** through the real dispatcher with a fake sender: exactly one attempt, no DB rows, an audit row, and the error surfaced.

## Tests still required (from the M18a brief; mandatory)
- **An embedded-broker integration test** using the existing MQTT test broker fixture used by `test_mqtt`/HA discovery tests (find it; don't write a new broker). Assert topic `msh/US/2/json/mqtt/`, QoS 1, retain false, and the exact JSON envelope, through `AlertDispatcher` handling a `ToneDetected`, not by calling the sender directly.
- **Truncation property, fixed:** the current assertion `result.endswith("…") or len(...) <= 20` is always true. Assert (a) `len(result.encode()) <= max_bytes` for max_bytes drawn from 1..200, (b) valid UTF-8, (c) if truncated, `result` without the trailing `…` is a prefix of the input, and (d) if not truncated, `result == input`.
- **Rate limiting through the dispatcher:** `min_interval_s` and `max_per_hour` each produce an `AlertAttempt` whose error is `rate_limited`, with no retries (exactly one attempt row).
- **Phases:** a target with `phases=["pre_alert"]` sends nothing for `recording_ready`/`closed`; `["recording_ready"]` sends on that phase only.
- **Reload:** changing a target's template via `reload` takes effect on the next call. A removed target cancels pending coalescing tasks without errors.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- No new dependencies. Use invented node ids and names only.
- **Secrets:** API responses mask secrets by key name through `api/deps.py` `_dump` → `mask_secrets`. Keep the inline broker field named `password` so it stays masked. Add a test that `GET /api/alert-targets` and `GET /api/alert-targets/{id}` return the Meshtastic `password` masked, never plaintext, and that audit before/after diffs don't contain it.
- Never `git add`, commit or push.

## Definition of done
- For every numbered bug, the report shows red-first, passing and a diff excerpt.
- `just check` passes. Paste the pytest and vitest summary lines, and state the pytest count before and after.
- `just ci-local` with port 8806 passes up to api-drift. If api-drift fails only on uncommitted generated files, paste `git diff --stat -- web/src/api`.
- The report maps each new test name to the requirement it covers.
