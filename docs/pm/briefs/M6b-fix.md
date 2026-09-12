# PM review: M6b fails. The e2e suite has never run and can't pass as written.

The restructure, the spectrum/sources/alerts/settings/analyze pages, the unit tests (36 passing, 80.9% branches) and the no-suppressions rule are all good. `just check`, `api-drift`, `security` and the build pass (PM re-verified).

But M6.9 was reported as "added, blocked by Chromium download". PM inspection shows the e2e harness is broken independently of the browser, so it would fail in CI too. Fix it and **actually run it**.

## Findings
1. **The launcher's config is invalid, so the server never starts.**
   - `web/e2e/serve.mjs` writes `config.yaml` with `ui_password` and `realtime` as top-level keys. Neither is an `AppConfig` field: `AppConfig` forbids extra keys, and `ui_password` is a **setting** (`TONEWATCH_UI_PASSWORD` env), not config.
   - It also writes **no source and no tone set**, and **no fixture WAV** is generated. The test "live call appears" can never see a call.
   - **Fix:** generate a fixture WAV with `tonewatch-gen`, or a tiny Python step: silence, then a two-tone page (for example 1000 Hz 1.0 s + 1500 Hz 3.0 s), then voice-like audio. Then write a **valid** config with one `file` source (`realtime: true` on the **source**, `loop: true`) and a matching tone set. Pass `TONEWATCH_UI_PASSWORD` through the environment.
2. **Nothing serves the UI.**
   - The API has no static/SPA mount, so Playwright at `127.0.0.1:8765` only reaches JSON routes.
   - **Fix, inside `web/` only as the brief required:** the launcher serves `web/dist` with a small Node static server and proxies `/api/*`, including the **WebSocket upgrade** for `/api/ws`, to the backend on a second port. Keep cookies same-origin through the proxy.
   - Document this in `web/e2e/README.md`. M8 will replace it with the backend serving the SPA.
3. **No readiness wait.** The CI job runs `node e2e/serve.mjs &` then starts Playwright immediately. The launcher must print a sentinel line only after the build finishes **and** `GET /readyz` returns 200 through the proxy. Use Playwright's `webServer` config with `url`, `reuseExistingServer: false` and `timeout: 180000` instead of a background shell job, locally and in CI.
4. **`just e2e` is Windows-only.** The recipe uses PowerShell `$env:` syntax, which breaks on Linux. Make it portable: set `PLAYWRIGHT_BROWSERS_PATH` via just's `export` or `env_var_or_default`, or have `playwright.config.ts` read it.
5. **The browser can't be downloaded on this network.** The Chromium download times out on both the sandbox and the PM host, but **Google Chrome and Microsoft Edge are installed** on this machine. In `playwright.config.ts`, use `channel: process.env.PLAYWRIGHT_CHANNEL` (for example `chrome` or `msedge`) when set, otherwise bundled Chromium, which CI keeps using. `just e2e` sets `PLAYWRIGHT_CHANNEL=chrome` on Windows and skips `playwright install` when a channel is set.
6. **Test naming:** fine as-is. The existing M6a suite serves as "restructure preserves m6a behaviour".

## e2e must prove
- **`live call appears and recording plays`:**
  1. Log in through the UI with the password.
  2. The dashboard shows a call for the fixture tone set within 10 s.
  3. Open the detail view: the `<audio>` element's recording URL returns **200 or 206** with an `audio/*` content type. Capture this with `page.waitForResponse`.
  4. `readyState ≥ 1`.
- **`create tone set through ui`:** fill the form, save, and assert the new tone set appears in the list **and** via `GET /api/tonesets` from the page context.
- **`websocket connects through proxy`:** the dashboard's live connection indicator reaches connected, or assert a WS frame is received.

## Definition of done
- `just e2e` **passes locally on this machine** using `PLAYWRIGHT_CHANNEL=chrome`. Paste the unfiltered Playwright summary (tests passed, duration).
- `just check`, pre-commit over all files, `just api-drift` and `just security` all exit 0; run `just check` last.
- The CI `e2e` job uses Playwright `webServer` (no background `&`), installs PortAudio and Chromium, and uploads the trace on failure.
- No backend source changes. You're still in the main checkout while M7 runs in a separate worktree.
