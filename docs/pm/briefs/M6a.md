# Brief: M6a Web UI: shell, dashboard, calls, tone sets (M6.1–M6.4)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium

## Goal
Build the first real UI on the generated API client: an authenticated, ingress-aware app shell, a live dashboard, a calls browser with an audio player, and tone set management. Work test-first with Vitest and Testing Library.

Before starting, read `AGENTS.md`, `PLAN.md` (M6, the web entries under Linting and quality standards), `docs/PROGRESS.md`, `web/` (package.json, eslint/tsconfig/vite/vitest configs), `web/src/api/openapi.json`, `web/src/api/generated/schema.d.ts`, `web/src/api/ws-messages.ts`, and the backend routes in `backend/src/tonewatch/api/routes/` (especially `auth.py` and `ws.py` for session, CSRF and WebSocket auth).

## Hard rule on evidence
Every behaviour claimed in your final message must name the test that proves it. No `eslint-disable`, `@ts-ignore`, `@ts-expect-error` or `/* istanbul ignore */` unless there's a same-line justification. The PM greps for these.

## In scope
M6.1, M6.2, M6.3, M6.4, and dependency hygiene. **Not** the spectrum, sources, alerts/settings, analyze or e2e pages; those are M6b.

## Required
1. **Dependency hygiene first.** `web/package.json` uses `"latest"` for most dependencies, which isn't reproducible. Replace every `latest` with a caret range matching the version currently in `pnpm-lock.yaml`. Keep the lockfile consistent (`pnpm install --frozen-lockfile` must pass). Then add the plan's stack:
   - `react-router` (v7, data router)
   - `@tanstack/react-query`
   - `openapi-fetch` (typed against the generated `paths`)
   - Tailwind v4 (`@tailwindcss/vite`)

   shadcn/ui components are optional; if you use them, vendor them under `src/components/ui`. Every new dependency must pass `just security` (licence and audit).
2. **M6.1 Shell (`src/app/`).**
   - **Base path:** `vite.config.ts` uses `base: './'`, and every API and WebSocket URL is built **relative to `document.baseURI`**, so the app works at `/` and under HA ingress (`/api/hassio_ingress/<token>/`). One module, `src/lib/urls.ts`, builds all URLs. Test it with jsdom under both base URIs.
   - **API client:** `src/api/client.ts` wraps `openapi-fetch` with `credentials: 'same-origin'`. It attaches `X-CSRF-Token` from the CSRF cookie on non-GET requests, and on 401 it routes to `/login`. It never stores a bearer token in `localStorage`; the browser UI uses the session cookie only.
   - **Auth:** a `/login` page (password form). If the backend reports that no password is configured, or the request is trusted ingress, go straight in; add a small backend endpoint `GET /api/auth/status` → `{authenticated, password_required, via}` if one is missing, with backend tests. Include logout.
   - **Layout:** a sidebar or top navigation. The light/dark theme follows `prefers-color-scheme`, has a toggle, and is persisted in `localStorage` inside try/catch. Include an error boundary and a 404 route.
   - **WebSocket:** `src/lib/ws.ts` is a typed client over `ws-messages.ts`. It authenticates by cookie (same origin), reconnects with backoff, re-subscribes after reconnecting, and exposes a `useSubscription(topic)` hook. Unit-test reconnect and resubscribe against a mock WebSocket.
3. **M6.2 Dashboard.**
   - A live call feed from the `events` topic, newest first, capped at 50 entries, where a click opens the call detail.
   - Per-channel level meters from `levels`: accessible `role="meter"` with `aria-valuenow`, plus a text dBFS value.
   - Feed-health badges from `FeedHealthChanged`, showing the reason text.
   - An empty state with a link to Sources.
4. **M6.3 Calls.**
   - A list with filters (source, tone set, date range) bound to URL search params, and cursor pagination using the API cursor.
   - **Detail:**
     - matched tone sets with detection times
     - a native `<audio controls>` player pointed at the recording URL **exactly as returned by the API** (already ingress-prefixed), with an mp3/opus format switch when both exist
     - an alert-attempts table (empty until M7)
     - a download link
5. **M6.4 Tone sets.**
   - A list with enabled toggles.
   - **Create/edit form:**
     - an ordered sequence editor for 1–8 tones: frequency, tolerance %, min_s, max_s
     - recording policy fields
     - alert target multi-select
   - Client-side validation mirrors the pydantic constraints (frequency 250–3000, tolerance 0.1–10, max ≥ min). Server 422 errors map onto fields by `loc`.
   - Delete asks for confirmation. A **409** shows the referrer list the API returns.
   - A **Test** button calls `POST /api/tonesets/{id}/test` and shows the resulting call appearing in the live feed.
   - legacy tones.cfg import is **out of scope** (blocked on the user's sample file, M8.4); show the button disabled with a tooltip.

## Accessibility
The `jsx-a11y` strict rules pass. Every form input has a label, and focus is managed on route change and dialog open. Add `@axe-core/react` or `vitest-axe` checks for the dashboard, calls list, call detail and tone set form, asserting no violations.

## Tests
- Vitest + Testing Library + MSW (`msw`) mocking the API from `openapi.json` paths.
- **Required named tests:**
  - `urls respect ingress base path`
  - `client sends csrf header on mutations`
  - `401 redirects to login`
  - `ws reconnects and resubscribes`
  - `dashboard shows live call from ws event`
  - `level meter is accessible`
  - `calls filters sync to url`
  - `call detail plays api-provided recording url`
  - `toneset form validates ranges`
  - `toneset 422 maps to fields`
  - `toneset delete 409 shows referrers`
  - `toneset test button triggers test endpoint`
  - `axe: no violations on key pages`
- Web coverage ≥80% lines and branches, enforced in `vitest.config.ts` thresholds.

## Constraints
- Backend changes are limited to the auth status endpoint and its tests, if needed.
- Don't modify PM-owned files: `.github/workflows/*` (except none), `scripts/license_check.py`, `docs/pm/*`.
- Regenerate the client with `just gen-api` if you touch the backend, and commit the generated files (`just api-drift` must pass).

## Definition of done
- `just check` exits 0 (it runs web lint, tsc and tests); run it last and paste the unfiltered tail.
- `just api-drift`, pre-commit over all files, and `just security` each exit 0.
- `pnpm --dir web build` succeeds.
- `docs/PROGRESS.md` ticks M6.1–M6.4.
- The final message has a claim → test table, the web coverage numbers, and screenshots are **not** needed.
