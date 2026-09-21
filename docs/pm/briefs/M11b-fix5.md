# Brief: M11b-fix5 — duplicated `recordings/` in the URL, a state that survives unload, and coverage at 88 %

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11b-entities`** (the PM pushed fix4; the branch is clean).

## Status
[PR #6](https://github.com/JustBeanie/ha-tonewatch/pull/6) after fix4: lint, typecheck, hassfest and hacs pass. The unload lifecycle fix was right, but three things remain.

```
FAILED test_setup_creates_expected_entities_and_unloads
  tests/test_entities.py:164: assert all(hass.states.get(entity_id) is None for entity_id in entity_ids)
  (async_unload returned True, entry.state is NOT_LOADED, async_block_till_done was awaited)

FAILED test_push_events_update_entities_and_fire_bus
  event_state.attributes["recording_url"]
    expected http://tonewatch.local:8099/api/recordings/call.mp3
    actual   http://tonewatch.local:8099/api/recordings/recordings/call.mp3

ERROR: Coverage failure: total of 88 is less than fail-under=90
```

1. **Product bug: the recording URL duplicates `recordings/`.** The event payload's path already contains the `recordings/` segment, and the entity prefixes `/api/recordings/` again. Build the URL from the payload correctly:
   - if the payload value is already absolute (`http://` or `https://`), use it as-is
   - otherwise join it against the base URL with `urljoin`/`yarl`, so no segment is duplicated and no double slash appears

   Check the **real** payload field names and shapes in the app repo (`backend/src/tonewatch/events.py` `RecordingReady`, `api/routes/ws.py`, and how `api/routes/recordings.py` serves them) instead of guessing. Cover both shapes with tests: a bare filename and a `recordings/...`-prefixed path.
2. **A state still exists after unload.** The entry unloads cleanly now, so something re-creates or retains a state.
   - First, make the failure legible: change the assertion to report **which** entity ids remain (e.g. `leftover = [eid for eid in entity_ids if hass.states.get(eid)]; assert not leftover, leftover`). CI then names them.
   - Likely cause: a coordinator listener still fires during or after platform teardown and calls `async_write_ha_state()`, putting the state back. `CoordinatorEntity` removes its listener in `async_will_remove_from_hass`, so check for any **extra** subscription your entities add (a raw `coordinator.async_add_listener`, a bus listener or a callback registered in `async_added_to_hass`) that isn't torn down.
   - Fix the cause and keep the assertion strict.
3. **Coverage is 88 % against the repo's 90 % gate.** Add behavioural tests for the uncovered branches (read the coverage report in the CI log or run coverage on the parts that import on Windows). Do not change the gate.

Pytest still cannot run on Windows; CI verifies. Never weaken an assertion.

## Evidence
- For items 1 and 2: the cause, the fix (file:line) and the covering test.
- The coverage number you expect after item 3, and the test names.
- `ruff` and `mypy` output. `git diff --stat`. Never write git state.
- **Honesty rule:** as always.

## Standing rules
- As in M11b. The app repo is read-only reference.
