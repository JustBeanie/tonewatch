# Brief: M11b-fix4 — unload swallows its result (product bug), and an HA `event` state is a timestamp

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11b-entities`** (the PM pushed fix3; the branch is clean).

## Status
[PR #6](https://github.com/JustBeanie/ha-tonewatch/pull/6) after fix3: lint, typecheck, hassfest and hacs pass; two test failures remain.

```
FAILED test_setup_creates_expected_entities_and_unloads
  tests/test_entities.py:163: assert all(hass.states.get(entity_id) is None for entity_id in entity_ids)
  (entry.state is NOT_LOADED, but entity states are still present)

FAILED test_push_events_update_entities_and_fire_bus
  tests/test_entities.py:199: assert event_state.state == "pre_alert"
  actual: '2026-09-21T00:34:51.466+00:00'
```

1. **Product bug: `async_unload_entry` ignores the platform unload result** (`custom_components/tonewatch/__init__.py`).
   - It calls `await hass.config_entries.async_unload_platforms(entry, PLATFORMS)` and discards the boolean, then returns `True` regardless. It also returns `True` **without unloading any platform** when the coordinator is missing from `hass.data`.
   - Use the standard shape: unload the platforms first, and only on success pop the coordinator and stop it; return the boolean.
   - Then **find out why states persist**. The entry reports NOT_LOADED while entity states remain, which suggests a platform did not unload cleanly. Instrument it locally if you can (`caplog`), or reason from the HA source, and fix the real cause. Candidates: a platform whose entities keep a listener that survives unload, `entry.async_on_unload(coordinator.async_stop)` racing the explicit `await coordinator.async_stop()`, or an entity that is never added to a platform. **Do not** change the test to accept lingering states.
2. **An HA `event` entity's state is the event's ISO timestamp**, not the event type. The type is in the attributes (`event_type`). Fix that assertion to check `event_state.attributes["event_type"] == "pre_alert"`, and assert the state parses as a timestamp. Check every other `event` assertion for the same mistake.
3. Re-read the file for other HA-semantics assumptions.

Pytest still cannot run on Windows; CI verifies. Never weaken an assertion to go green.

## Evidence
- The unload fix (file:line), your explanation of why the states lingered, and the test that proves they are gone.
- The corrected event assertions.
- `ruff` and `mypy` output. `git diff --stat`. Never write git state.
- **Honesty rule:** as always.

## Standing rules
- As in M11b.
