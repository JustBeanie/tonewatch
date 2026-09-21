# Brief: M11b-fix6 — find out why every entity state survives unload (use CI as your debugger)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11b-entities`** (clean).

## Status
The recording-URL fix is in and correct. **The PM reverted your `__init__.py` change that called `hass.states.async_remove()` for every registry entity during unload**: that deletes the symptom and hides the defect. Don't reintroduce it.

CI now names the leftovers, and it is **every** entity:

```
AssertionError: ['event.tonewatch_instance_1_ems', 'event.tonewatch_instance_1_fire',
 'button.tonewatch_instance_1_test_ems', 'button.tonewatch_instance_1_test_fire',
 'sensor.tonewatch_instance_1_last_call', 'binary_sensor.tonewatch_instance_1_...', ...]
```

Facts established:
- the test uses the real path: `entry.add_to_hass(hass)`, then `await hass.config_entries.async_setup(entry.entry_id)`
- `await hass.config_entries.async_unload(entry.entry_id)` returns True, `entry.state is ConfigEntryState.NOT_LOADED`, and `await hass.async_block_till_done()` runs **before** the leftover assertion
- `async_unload_entry` unloads platforms first, returns False on failure, and only then stops the coordinator
- each platform's `async_setup_entry` is the standard `async_add_entities([...])` shape

So `async_unload_platforms` is reporting success while the entities stay in the state machine. That is unusual, so **find the mechanism before changing anything**.

## Required
1. **Instrument through CI**, since you cannot run pytest locally. In a temporary commit-free edit, capture and print evidence that will appear in the CI log:
   - `caplog.set_level(logging.DEBUG)` around the unload, then print the records: HA logs entity-platform teardown and swallows exceptions raised in `async_will_remove_from_hass`
   - print `entry.state`, and the platforms recorded on the entry
   - assert on `hass.data["tonewatch"]` after unload

   Ask the PM to push, read the CI log, then keep narrowing. State clearly in your report which commit is instrumentation so the PM can drop it.
2. **Likely mechanisms, in order:**
   - an exception inside `ToneWatchEntity`/`CoordinatorEntity` teardown (for example `async_will_remove_from_hass`, or a property that raises once `hass.data` no longer has the coordinator), logged and swallowed, leaving the state behind
   - an extra subscription your entities register that keeps a strong reference (a raw `coordinator.async_add_listener`, a bus listener, or a task)
   - the monkeypatched `async_start` in the test fixture (`_start`) leaving the coordinator in a state where teardown raises
3. **Fix the real cause**, keep the strict leftover assertion, and remove all instrumentation in the final version.
4. Coverage must still clear the repo's 90 % gate.

## Evidence
- The CI log excerpt that identified the cause, quoted.
- The fix (file:line) and why it resolves it.
- `ruff` and `mypy` output, and `git diff --stat`. Never write git state.
- **Honesty rule:** as always. If you conclude the test's expectation is wrong after all, prove it from the HA source and say so.

## Standing rules
- As in M11b. Never weaken an assertion, and never remove states by hand to make a test pass.
