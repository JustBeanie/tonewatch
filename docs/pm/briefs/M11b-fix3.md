# Brief: M11b-fix3 — the three remaining failures are wrong test expectations, not product bugs

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11b-entities`** (the PM pushed fix2; the branch is clean).

## Status
[PR #6](https://github.com/JustBeanie/ha-tonewatch/pull/6) after fix2: lint, typecheck, hassfest and hacs pass. Unique ids are now correct. Three failures remain, and the PM's reading is that **the tests are wrong, not the integration**. Confirm that from the HA source before changing anything, and say so in your report if you disagree.

```
FAILED test_setup_creates_expected_entities_and_unloads
  tests/test_entities.py:160: assert not er.async_entries_for_config_entry(registry, entry.entry_id)
  -> still lists sensor.tonewatch_instance_1_last_call etc.

FAILED test_push_events_update_entities_and_fire_bus
  tests/test_entities.py:191: assert event_state is not None

FAILED test_feed_switch_button_disconnect_and_secret_redaction
  tests/test_entities.py:236: assert north_state is not None
```

1. **Unload does not clear the entity registry.** In Home Assistant, registry entries survive an unload and are removed only when the config entry is **removed** (`async_remove`). Assert what unload actually guarantees:
   - `await hass.config_entries.async_unload(entry.entry_id)` returns True and `entry.state is ConfigEntryState.NOT_LOADED`
   - the entities' **states** are gone from `hass.states`
   - optionally, that a following `async_remove` does clear the registry

2. **`hass.states.get(...)` returns None because the entity ids are guessed.** Don't hard-code slugs. Resolve each entity id from the registry by unique id:
   ```python
   registry = er.async_get(hass)
   entity_id = registry.async_get_entity_id("event", DOMAIN, "instance-1_event_fire")
   ```
   Then read `hass.states.get(entity_id)`. Do this for every state assertion, and drop the hand-written `sensor.tonewatch_instance_1_...` strings.
   - If a lookup legitimately returns `None`, that **is** a product bug: report it instead of weakening the assertion.
   - After each pushed frame, `await hass.async_block_till_done()` before asserting.

3. Re-read the whole test file once more for other assumptions about entity ids, registry behaviour or timing.

Pytest still cannot run on Windows; CI is the verification. Do not weaken any assertion to make it pass: the point of these tests is that pushing an event really updates a real entity.

## Evidence
- For each of the three tests: the wrong assumption, the corrected assertion, and the HA behaviour that justifies it.
- `ruff` and `mypy` output. `git diff --stat`. Never write git state.
- **Honesty rule:** as always.

## Standing rules
- As in M11b.
