# Brief: M6b Web UI: structure, spectrum, sources, alerts/settings, analyze, e2e (M6.5–M6.9)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium

## Goal
Finish the web UI. Restructure the M6a code first, then add the frequency counter/spectrum, sources, alerts and settings, and analyze pages, plus a real browser end-to-end test.

Before starting, read `AGENTS.md`, `PLAN.md` (M6), `docs/PROGRESS.md`, `docs/pm/reports/M6a-*.md`, all of `web/src`, `web/tests/m6a.test.tsx`, `web/src/api/{openapi.json,ws-messages.ts}`, and the backend routes `backend/src/tonewatch/api/routes/{config,system,analyze,ws}.py`.

## Parallel-work note
Another engineer is building alerts (M7) in a separate git worktree and will change `backend/src/tonewatch/alerts/*`, `events.py` and `config`. **Stay in `web/`**, apart from the e2e launcher described below. Don't edit `backend/src/tonewatch/**`. If the UI needs a backend change, write `BLOCKED: need <endpoint>` and build against what exists.

## Hard rule on evidence
Every claim cites its proving test. There must be no `eslint-disable`, `@ts-ignore`, `@ts-expect-error`, `istanbul ignore` or `test.skip` anywhere.

## Required
1. **Restructure first, with no behaviour change.**
   - Split the 546-line `web/src/App.tsx` into `src/app/{router.tsx,Shell.tsx,Boundary.tsx}`, `src/features/{auth,dashboard,calls,tonesets}/…` and `src/components/…`.
   - `App.tsx` keeps only providers plus the router.
   - Every existing M6a test passes **unmodified except import paths**. Commit-sized, reviewable moves.
2. **M6.5 Frequency counter / spectrum (`features/spectrum`).**
   - Pick a source, then subscribe to `spectrum:<source_id>` over the WebSocket.
   - Draw a `<canvas>` magnitude plot with a frequency axis labelled 250–3000 Hz.
   - Readouts for dominant frequency (1 decimal place), purity and level, updated at the stream rate. Pause/resume. Unsubscribe on unmount, and assert in a test that the unsubscribe is actually sent.
   - A **"Capture tone"** button snapshots the dominant frequency and opens the tone set form with `freq_hz` prefilled.
   - **Accessibility:** the canvas has an `aria-label` plus a visually hidden live region announcing the dominant frequency at most once per second.
3. **M6.6 Sources (`features/sources`).**
   - CRUD over `/api/sources` with a type switch: soundcard (device picker from `GET /api/devices`, plus channel), stream (URL), rtlsdr (frequency in MHz shown and stored as Hz, gain, ppm, squelch), and file.
   - Live level preview per source from the `levels` topic.
   - The stream URL field rejects non-`http(s)`/`rtsp(s)` schemes client-side, with a message noting the server validates too.
   - Map 422 errors to fields, like M6a.
4. **M6.7 Alerts and settings.**
   - **Alerts (`features/alerts`):** CRUD over `/api/alert-targets` for the mqtt, webhook and script types.
     - Webhook secrets are **write-only in the UI**: never displayed back, with a "secret set" indicator and a replace action.
     - Script targets show a prominent warning, and surface the server's 403 ("script targets are disabled on this server") clearly.
     - A "Send test" action uses `POST /api/tonesets/{id}/test` for a chosen tone set routed to the target.
   - **Settings (`features/settings`):** read-only display of what the API exposes today (auth status, version via readyz if available). Everything not yet exposed is listed as "configured in config.yaml / add-on options", with no fake controls.
5. **M6.8 Analyze (`features/analyze`).**
   - WAV upload with a client-side 20 MB check (the server enforces it too), and progress.
   - Render the returned schema as:
     - a segment timeline: an SVG bar per segment on a time axis, labelled with frequency
     - a detections table
   - Handle 413/415 errors with clear messages.
6. **M6.9 Playwright e2e (`web/e2e/`).**
   - The Docker compose stack arrives in M8, so the e2e **launcher is a script**, `web/e2e/serve.mjs` or `backend/scripts/e2e_server.py`. It:
     - creates a temp data dir with a `config.yaml` containing a file source that points at a generated fixture WAV (use `tonewatch-gen` to create a two-tone page plus voice) with `realtime: true`, and a matching tone set
     - runs Alembic, then `tonewatch serve` on an ephemeral port with a known UI password, and prints the URL
     - builds the web assets so FastAPI serves them. If the API doesn't serve the SPA yet, serve `web/dist` from the launcher with a proxy to the API and document it; don't touch backend code.
   - **Test:** log in → the dashboard shows the live call **within 10 s** → open the call detail → the `<audio>` element loads (`readyState ≥ 1` and a successful network response for the recording URL).
   - Also run the tone set create flow through the real UI.
   - `just e2e` runs it, installing Chromium via `pnpm exec playwright install chromium` into the user cache. Add a CI job `e2e` to `ci.yml` (you may edit `ci.yml` for this job only): Linux, PortAudio via apt, Chromium, upload the trace on failure.
7. **Coverage and accessibility.** Web coverage ≥80% lines **and** branches with real tests (branches is 80.34% today, so add tests rather than flirting with the gate). Add vitest-axe checks for the spectrum, sources, alerts, settings and analyze pages.

## Required named tests
- `restructure preserves m6a behaviour` (the existing suite, run as-is)
- `spectrum subscribes and unsubscribes on unmount`
- `capture tone prefills toneset form`
- `spectrum live region throttled to 1 per second`
- `sources rtlsdr mhz converts to hz`
- `sources device picker lists devices`
- `stream url rejects file scheme`
- `webhook secret is write-only`
- `script target 403 is explained`
- `analyze rejects oversize before upload`
- `analyze renders segment timeline and detections`
- `axe: no violations on m6b pages`
- e2e: `live call appears and recording plays`, `create tone set through ui`

## Definition of done
- `just check`, `just e2e`, `just api-drift`, pre-commit over all files and `just security` all exit 0, plus `pnpm --dir web build`. Run `just check` last and paste the unfiltered tail.
- `docs/PROGRESS.md` ticks M6.5–M6.9.
- The final message has a claim → test table and the web coverage numbers.
