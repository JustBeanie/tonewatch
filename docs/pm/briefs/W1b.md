# W1b brief: the backend serves the SPA, plus a real Playwright e2e (M6.9 redo)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, **high**

## Why this exists
The first two M6.9 attempts were rejected. The last harness passed only because its Node proxy **rewrote `GET /api/calls/{id}` to inject a fake recording**. It also rewrote the WebSocket `Origin`, injected `<base href="/">` into the HTML, and killed itself on idle timers.

W1a has since made the real app record. Now remove the proxy entirely:
- The backend serves the built SPA on the same port, which is how Docker (M8) and the HA add-on (M10) will run it.
- The e2e drives that real single-port app.

**Hard rule: the harness may start processes, generate fixture audio and write config. It may NOT sit between the browser and the app, rewrite any request or response, or mock any API.** Any test double in the e2e path is an automatic fail.

Read these before starting:
- `AGENTS.md`, `PLAN.md` (M5.2 ingress, M6, M8, M10), `docs/PROGRESS.md`
- `backend/src/tonewatch/{settings.py,api/app.py,api/auth.py}`
- `web/vite.config.ts`, `web/src/app/router.tsx`, `web/src/lib/urls.ts`
- `docs/pm/briefs/M6b-fix.md` (its e2e requirements still apply, **except the Node proxy**)

## Required
1. **SPA serving in the backend.**
   - Add a `web_root` setting: default `<package>/web_dist` when that exists, otherwise `<repo>/web/dist` when running from source, otherwise the SPA is disabled with a clear log line.
   - Serve the static assets. `index.html` is the fallback for GET requests that aren't `/api/*`, `/healthz`, `/readyz` or an existing asset, with `Accept` including `text/html`.
   - Hashed assets (`/assets/*`) get `Cache-Control: public, max-age=31536000, immutable`; `index.html` gets `no-cache`.
   - The CSP on HTML allows `'self'` scripts/styles/connect (including same-origin `ws:`/`wss:`) and nothing inline unless you prove the Vite build needs it. Don't weaken the API responses' CSP.
   - Tests in `backend/tests/integration/test_spa.py`:
     - `test_spa_served_with_history_fallback`
     - `test_spa_does_not_shadow_api_routes_or_401s` (an unknown `/api/x` returns a JSON 404, and a protected route unauthenticated returns 401 JSON, not HTML)
     - `test_spa_html_csp_allows_self_only`
     - `test_static_assets_have_immutable_cache_headers`
     - `test_spa_path_traversal_refused` (`/assets/../../api_token` and encoded variants)
2. **Deep links and ingress must work without `<base>` injection.**
   - Diagnose why the rejected harness needed `<base href="/">`: relative `./assets/...` URLs resolve against `/tonesets/` on a deep-link reload.
   - Fix it in the product so all three of these load:
     - (a) a direct reload of `/tonesets/new` at the root
     - (b) the same under an HA ingress prefix such as `/api/hassio_ingress/<token>/tonesets/new`, where the backend knows the prefix from `X-Ingress-Path`
     - (c) plain `/`
   - Two acceptable approaches:
     - The backend rewrites or sets the document base from the trusted ingress path (only for the trusted ingress source per `auth.py`, otherwise `/`).
     - A root-relative-safe asset strategy.
   - Write an ADR `docs/decisions/0005-spa-base-path.md` explaining the choice.
   - Tests:
     - `test_spa_deep_link_assets_resolve` (backend: the HTML for `/tonesets/new` references assets that return 200 when resolved against that URL)
     - `test_spa_ingress_prefix_base` (trusted ingress uses the prefix; the same header from an untrusted IP is ignored)
3. **Playwright e2e against the real app.** `web/e2e/`, `web/playwright.config.ts`, `just e2e`, and the CI `e2e` job.
   - **Launcher** (`web/e2e/start.mjs`, or Playwright `globalSetup` plus `webServer`):
     - Build the web app.
     - Generate the fixture WAV **with the Python generator** (`tonewatch-gen` or `tonewatch.dsp.generator`): silence, a two-tone page (1000 Hz 1.0 s + 1500 Hz 3.0 s), then voice-like audio.
     - Write a **valid** config with one `file` source (`realtime: true`, `loop: true`) and a matching tone set.
     - Start `tonewatch serve` on the e2e port with `TONEWATCH_UI_PASSWORD` in the environment.
     - Playwright `webServer.url` points at `/readyz`, with `reuseExistingServer: false` and `timeout: 180000`.
   - **No idle or fixed self-termination timers.** Teardown is Playwright's `webServer` shutdown.
     - On Windows, verify the backend process tree is gone afterwards: no listener on the port and no orphan `python`/`uv` processes. Report the command you used.
     - If Windows needs help, handle `SIGTERM`/`SIGINT` **and** stdin close to kill the child tree. Don't use timers.
   - **Browser:** `channel: process.env.PLAYWRIGHT_CHANNEL || undefined`. `just e2e` is portable (no PowerShell-only syntax). On Windows it sets `PLAYWRIGHT_CHANNEL=chrome` and skips `playwright install`.
   - **Specs** (exact names):
     - `live call appears and recording plays`:
       1. Log in through the UI.
       2. A call for the fixture tone set is visible within 15 s.
       3. Open its detail view. `page.waitForResponse` captures the `<audio>` recording request with status 200 or 206 and an `audio/*` content type, **served by the backend from a real recording file**.
       4. `readyState ≥ 1`.
     - `create tone set through ui`: the form, then save, then it appears in the list **and** via `GET /api/tonesets` from the page context.
     - `websocket connects`: the dashboard's live connection indicator reaches connected, and at least one frame is received.
     - `deep link reload renders`: `page.goto('/tonesets/new')` then `page.reload()` shows the form heading, and no request returns 404.
   - **CI `e2e` job:**
     - Ubuntu, PortAudio apt, `playwright install --with-deps chromium`, and `pnpm exec playwright test` (webServer-managed, no `&`).
     - Upload `web/test-results` and `playwright-report` on failure.
     - Actions pinned by SHA, `permissions: {contents: read}`, and `persist-credentials: false`.
   - Update `web/e2e/README.md`.
4. Tick **M6.9** only when `just e2e` passes locally. Add `W1b.1`–`W1b.3` under `## W1: Wiring` in `docs/PROGRESS.md`.

## Constraints
- **Allowed changes:** `backend/src/tonewatch/{settings.py,api/app.py}` plus a new `api/spa.py`, backend tests, and `web/` (config, e2e and any base-path fix), plus `justfile`, `.github/workflows/ci.yml`, `docs/`.
- **No** `pragma: no cover`, no unjustified suppressions, and no lowered coverage gates (api ≥90 per module).
- **Web:** eslint may ignore `e2e/**` only if a separate `tsc --noEmit` pass covers the e2e files. Otherwise lint them.

## Definition of done
- Paste the **unfiltered** Playwright summary from `just e2e` with `PLAYWRIGHT_CHANNEL=chrome`: 4 passed, with the duration. `just e2e` must exit 0, and you must show that exit code.
- Show the post-teardown orphan-process check output.
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Then `just check` runs **last**; paste its unfiltered tail.
- The final message has a **claim → test** table and states explicitly that no request or response is intercepted, mocked or rewritten in the e2e path.
