# Brief: M5b WebSocket, discovery and the generated API client (M5.4–M5.6)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium

## Goal
Add live push to the API, make ToneWatch discoverable by Home Assistant, and generate the typed web client from OpenAPI with a drift check.

Before starting, read `AGENTS.md`, `PLAN.md` (M5, M10, M11), `docs/PROGRESS.md`, `backend/src/tonewatch/api/` (the whole package, especially `auth.py`, `app.py` and `routes/`), `events.py`, `pipeline/channel.py`, `dsp/spectrum.py`, `settings.py`, `web/package.json` and the `justfile`.

## Hard rule on evidence
PM review found overclaimed verification three times. **Every behaviour claimed in your final message must name the test function that proves it**, and that test must fail if the behaviour is removed. Claims without tests will be treated as not done.

## In scope
M5.4, M5.5, M5.6.

## Required design
- **M5.4 WebSocket `/api/ws` (`api/routes/ws.py`).**
  - **Authentication happens during the handshake**, with the same rules as REST: a bearer token via the `Authorization` header **or** the `Sec-WebSocket-Protocol` subprotocol `tonewatch.bearer.<token>` (browsers can't set headers), a session cookie plus `Origin` check, or trusted ingress.
  - Reject unauthenticated connections with close code **4401 before accepting any data**.
  - For cookie-authenticated connections, reject a cross-origin `Origin` with close code **4403**. This is the WebSocket CSRF equivalent.
  - **Protocol:** JSON messages `{"type": ..., "data": ...}`. The client sends `{"type":"subscribe","topics":["events","levels","spectrum:<source_id>"]}`, and the server acknowledges.
  - **events:** every domain event from the `EventBus`, serialised with explicit schemas (UUIDs and datetimes as ISO strings).
  - **levels:** per-channel RMS dBFS and peak at ≤5 Hz. The channel must publish these cheaply; add a `ChannelLevel` event, or a level tap throttled in the channel.
  - **spectrum:<source_id>:** only while at least one client subscribes. Stream dominant frequency, purity, level and a downsampled magnitude array (≤256 bins, 250–3000 Hz) at ≤5 Hz. Add a subscription-count gate so the channel does no spectrum work with no subscribers.
  - **Backpressure:** each client gets a bounded send queue. A slow client drops the oldest **levels/spectrum** messages, but **events are never dropped silently**: if the events queue overflows, close with code 1013. There's a 30 s ping/pong heartbeat, and a max of 20 concurrent connections (reject extras with 1013).
  - Unsubscribe on disconnect, with no leaked bus subscriptions or tasks.
- **M5.5 Discovery.**
  - **`integrations/zeroconf.py`:** advertise `_tonewatch._tcp.local.` with the port and TXT records `version`, `api=/api`, and `instance_id` (a stable UUID stored in the data dir). **Never put the token in TXT.** Enable it with `settings.zeroconf_enabled` (default true, false in add-on mode). Use the `zeroconf` package's async API. Unregister on shutdown.
  - **`integrations/supervisor.py`:** in add-on mode, `POST http://supervisor/discovery` with `SUPERVISOR_TOKEN` and `{"service": "tonewatch", "config": {"host": <addon hostname>, "port": <port>}}`. Retry with backoff, run it once at startup, and treat failure as non-fatal. Use `httpx.AsyncClient`, mocked in tests.
- **M5.6 OpenAPI and client.**
  - `just gen-api` exports `openapi.json` from `create_app` (no server needed) to `web/src/api/openapi.json`, then runs `openapi-typescript` to `web/src/api/generated/schema.d.ts`. Add `openapi-typescript` as a web dev dependency.
  - **The WebSocket message schemas** (not in OpenAPI) go in `web/src/api/ws-messages.ts`, generated from pydantic models with a small script. It **may not be hand-written**, because it has to stay in sync with the backend.
  - **Drift check:** a new CI job in `ci.yml` named `api-client-drift` runs `just gen-api` and then `git diff --exit-code web/src/api`. You **may** edit `ci.yml` for this one job only. Locally, `just check` does not run it (it needs pnpm install), but add a `just api-drift` recipe.
  - Commit the generated files. Exclude them from prettier and eslint if their generator output isn't formatted, via the ignore files.

## Tests
- **WebSocket**, with `starlette.testclient.TestClient` websocket or `httpx-ws`:
  - handshake auth via header, subprotocol, cookie + same origin, and ingress
  - 4401 unauthenticated; 4403 cross-origin cookie
  - subscribe ack
  - a published `ToneDetected` arrives with ISO fields
  - level rate ≤5 Hz with an injected clock
  - spectrum only computed while subscribed (channel spy)
  - slow client drops levels but not events, and events overflow closes with 1013
  - the 21st connection is rejected
  - disconnect cleans up subscriptions (bus subscriber count returns to baseline)
- **zeroconf:** register/unregister against a mocked `AsyncZeroconf`; TXT contents; token absent; disabled in add-on mode.
- **supervisor discovery:** payload and headers; retries; non-fatal failure; skipped outside add-on mode.
- **gen-api:** the export is deterministic (two runs give byte-identical output); `ws-messages.ts` is generated.
- Coverage: `api` ≥90% per module; add `integrations` at ≥90%.

## Constraints
- Don't modify PM-owned files except the single `api-client-drift` job in `ci.yml`: `scripts/license_check.py`, `.github/workflows/security.yml`, `docs/pm/*`.
- New dependencies pass `just security`.

## Definition of done
- `just check` exits 0 (run it last; paste the unfiltered tail), `just api-drift` exits 0, pre-commit over all files exits 0, and `just security` exits 0.
- `docs/PROGRESS.md` ticks M5.4–M5.6.
- The final message has a claim → proving-test table.
