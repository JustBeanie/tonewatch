# Brief: M11b-fix — the health fetch calls a route that does not exist, and health is derived wrongly

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch` (your uncommitted work stays). `docs/pm/briefs/M11b-entities.md` still applies.

## PM review
The platforms, the state projection, the optimistic switch write and the bus event all look right. Three things to fix. **Your sandbox cannot run the HA test stack on Windows** (`fcntl`, and `lru-dict` needs MSVC), which you reported honestly. That's expected: this repo's tests run on Linux in GitHub CI, which the PM will trigger. So **write the tests carefully by reading the existing ones**, and say clearly in your report that you could not execute them.

1. **`/api/health` does not exist.** `api.py` `_async_initial_fetch` fetches `GET /api/health`. The app serves:
   - `GET /api/admin/health` (authenticated, the full `HealthResponse`)
   - `GET /healthz` and `/readyz` (liveness only, no sources)

   Use `/api/admin/health`. Today the wrong path raises, is swallowed by the warning handler, and every feed-health sensor silently stays unknown.
2. **Feed health is derived from keys that aren't in the response.** Each `sources[]` item has `id`, `name`, `realtime_factor`, `dropped_frames`, `restarts`, `last_error`, `squelch`, `feed_health_history` (a list of `{healthy, at}` entries). There is no `healthy` key, and `last_error is None` is not the same as healthy. Derive it from the **last** `feed_health_history` entry's `healthy`, defaulting to unknown when the history is empty, exactly as the app's `/metrics` renderer does (`backend/src/tonewatch/api/metrics.py`, `tonewatch_feed_healthy`). Read that file.
3. **Tests for both:** a fixture health payload shaped exactly like `HealthResponse` (copy the shape from `backend/src/tonewatch/api/routes/admin.py` `health()`; don't invent it) drives the per-source binary sensors, and the initial fetch requests `/api/admin/health`. Add a test that an initial-fetch failure leaves entities unavailable rather than silently healthy.

## Also
- `_async_set_enabled` catches bare `Exception` to revert. Narrow it to the aiohttp and OS error types the coordinator already handles, plus `TimeoutError`, and re-raise.
- The device info sets `name: "ToneWatch"` for every instance. Include the instance id or host so two ToneWatch servers in one HA don't collide, and set `configuration_url` to the app's base URL.

## Evidence (the report is rejected without it)
- A table of the four items with the code change (file:line) and the test that covers it.
- `just lint` and `just typecheck` output (those do run on Windows), plus an explicit statement that pytest could not run locally and why.
- `git diff --stat`.
- **Honesty rule:** as always. Do not claim tests pass.

## Standing rules
- As in M11b. Never write git state; the PM pushes a branch and lets GitHub CI run the tests.
