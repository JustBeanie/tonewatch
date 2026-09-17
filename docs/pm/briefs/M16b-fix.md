# Brief: M16b-fix — Save agency fails in the real app; errors render as "[object Object]"

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-ec49-7183-af57-74f0736f51dd`; if resume fails, this brief is self-contained) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m16b` (your uncommitted M16b work stays). **E2E port:** `TONEWATCH_E2E_PORT=8828`. Environment and git rules are the same as `docs/pm/briefs/M16b-agencies-map-ui.md`, which still applies in full.

## Verdict on M16b: FAIL
**PM verified and kept:**
- Agencies list and editor, and Map page on Leaflet `circleMarker` (no default icon PNGs)
- The tile layer only when `tile_url` is set
- `prefers-reduced-motion` handling
- The calls agency filter (the backend already supports `agency_id`)
- `leaflet` and `@types/leaflet` only
- 79 Vitest tests
- `test_s4_security.py` has no diff

**Why it fails:**
- **The PM ran `just e2e` on the host (port 8828), where the launcher works.** The 6 existing specs pass, but **your new agency scenario fails**: `expect(page).toHaveURL(/\/agencies$/)` stays on `/agencies/new`.
  - After clicking **Save agency**, the page shows the alert text **`[object Object]`**.
  - A screenshot and Playwright's error context are at `C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\m16b-e2e-fail\`.
  - So the save request is rejected by the real backend, which your mocked Vitest tests never exercised. The error UI also can't display FastAPI's error shape.
- **Bug 1, the save fails:** find out exactly why (capture the request body and the response status and body in the e2e run, e.g. `page.on("response")` for `/api/agencies`, and paste it). Fix the payload or the form so a valid agency with typed coordinates and a linked tone set saves. Don't loosen backend validation to make it pass unless the backend is provably wrong; if it is, show the failing backend test first.
- **Bug 2, error rendering:** `errorText` in `AgencyForm.tsx` (~line 30) assumes `detail` is a string. FastAPI 422 bodies use `detail: [{loc, msg, type}, ...]` (and this app sometimes uses a string). Render both shapes as readable text (e.g. `coverage: must be a closed ring`). Check the other new components for the same pattern.
- **Bug 3, layout:** in "Linked tone sets" the checkboxes sit on separate lines from their labels (see the screenshot). Each checkbox must be inline with its label, and the label must be clickable.
- **E2E robustness:**
  - `if (await fixtureTone.count()) await fixtureTone.check();` silently skips linking. Make it unconditional, so the test fails if the fixture tone set isn't listed.
  - The e2e file source plays the fixture page once at startup, **before** your test creates the agency. The call's agency is a **snapshot taken at match time** (M16), so a call detected before the link can't show "Fixture Agency", and the map pulse needs an *active* call.
  - Make the scenario deterministic without weakening it. Options: trigger a fresh detection after linking via the existing test-trigger endpoint (`POST /api/tonesets/{id}/test`, used by the UI's test button), or extend `scripts/e2e_fixture.py` to configure the agency up front. State which you chose and why.
  - The pulse assertion must happen while the call is active.

## Evidence (the report is rejected without it)
- The captured failing request and response (status and body) from before your fix.
- **A host-equivalent e2e run of the full spec file:** all 7 tests passing, pasted. If the launcher hangs at teardown after the tests print, paste the per-test lines, which is acceptable.
- A Vitest test for `errorText` covering the list-shaped 422, the string detail and the network-error shapes. Show it failing first.
- `just check` green.

## Standing rules
- As in M16b. Never edit `docs/pm/**` or `PLAN.md`. Never write git state. No new dependencies.
