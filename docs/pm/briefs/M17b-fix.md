# Brief: M17b-fix — finish the CAD UI evidence, harden the incidents endpoint, regenerate the client

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0afb0-5a94-7211-a8fd-6d4846444485`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m17b` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8832`. `docs/pm/briefs/M17b-cad-ui.md` still applies in full.

## Verdict on M17b: PARTIAL
**PM verified and kept:**
- The incident card, live badge (a lossless same-tick test) and dashboard panel with its cap.
- Agency and map recent incidents, and the unmatched agencies page.
- The CAD feed form: its test proves no `"[REDACTED]"` is ever sent; `CadFeeds.tsx:65` deletes the empty or redacted password.
- No `console`/`document.title` use in `features/cad`. `just check` passed with 608 backend tests, and web coverage is 87.98 % statements / 80.48 % branches.

**Why it isn't a pass:**
1. **The generated client wasn't regenerated.** `web/src/api/openapi.json` changed but `web/src/api/generated/schema.d.ts` didn't, so `api-drift` fails. Run `just gen-api`.
2. **The mandatory Playwright scenario G is missing, and `ci-local` wasn't run.** Your report says so honestly, but both are required.
3. **Endpoint problems in `GET /api/cad/incidents`:**
   - `links = select(CallCadIncident)` loads **every** link row on every request, which is unbounded. Query only the links for the returned incidents: `where (feed_id, incident_id)` is in the page, or join.
   - `status` is a free string (1–30 chars). Make it `Literal["active", "closed"]`, so anything else gives 422.
   - The test calls the route function directly. The brief required ASGI tests: 401 without auth; 422 for `limit=0`, `limit=101` and a bad `status`; `configured_only` filtering; the link `call_id` present; and a `caplog` check with no incident fields.
4. **The evidence table is missing** (test to letter, with its failing and passing lines).

## Required
- Fix items 1–3.
- **Add Playwright G** to `web/e2e/tonewatch.spec.ts`:
  - create a CAD feed through the Settings UI with an invented host (it stays disconnected, and no broker is needed)
  - assert it's listed with disconnected health
  - edit it with the password left empty and save successfully
  - open the unmatched agencies page (the empty state is fine)
  - no external requests (`page.on("request")`)
  - Make sure the feed runner's reconnect attempts to the invented host don't slow or break the other specs (e.g. the invented host is `127.0.0.1` on an unused port, so failures are fast). Delete the feed at the end of the test.

## Evidence (the report is rejected without it)
- The test table with failing and passing lines, including the new ASGI tests and G.
- `just check` green (counts and web coverage).
- **`just e2e` on port 8832, with per-test lines for all 8 specs.**
- `just ci-local` through `api-drift` (it must pass now that the client is regenerated; paste the tail).
- `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M17b. **`main` has moved** (secret-masking fix `1fd0965`). Don't touch `api/audit.py`, `api/deps.py` or `logging.py`. A parallel coverage engineer is adding tests under `backend/tests/` for alerts and pipeline, so don't edit those files.
