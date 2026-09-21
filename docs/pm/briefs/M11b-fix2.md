# Brief: M11b-fix2 — three CI failures from the first Linux run of your tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c0de-790a-7a43-a224-30f4e5e1c2ea`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11b-entities`** (the PM pushed your work; the branch is checked out and clean). `docs/pm/briefs/M11b-entities.md` and `M11b-fix.md` still apply.

## Status
The PM opened [PR #6](https://github.com/JustBeanie/ha-tonewatch/pull/6). On Linux CI: **lint, typecheck, hassfest and hacs pass**; the `test` job fails with three failures. That job is the first real execution of these tests, so these are ordinary first-run defects, not flakes.

```
FAILED tests/test_entities.py::test_setup_creates_expected_entities_and_unloads
  tests/test_entities.py:134: AssertionError
  Extra items in the left set:  'instance-1_last_call_', 'instance-1_call_active_'
  Extra items in the right set: 'instance-1_last_call',  'instance-1_call_active'

FAILED tests/test_entities.py::test_push_events_update_entities_and_fire_bus
  tests/test_entities.py:188: TypeError: 'StateMachine' object is not subscriptable

FAILED tests/test_entities.py::test_feed_switch_button_disconnect_and_secret_redaction
  tests/test_entities.py:226: TypeError: 'StateMachine' object is not subscriptable
```

## Required
1. **Unique ids for the singleton entities.** `ToneWatchEntity.__init__` builds `f"{instance_id}_{kind}_{item_id}"`, which leaves a trailing underscore when `item_id` is empty (`sensor.last_call`, the call-active binary sensor). Build the id from the non-empty parts, so it is `instance-1_last_call`, not `instance-1_last_call_`. **Decide the canonical form and make the code and the test agree**; the test's expectation (no trailing underscore) is the right one.
2. **`hass.states` is not subscriptable.** Use `hass.states.get("entity.id")` in those tests and assert on `.state`/`.attributes`.
3. Re-read the whole test file for the same two mistakes elsewhere, and for any other API misuse you can catch by reading (`async_fire_time_changed`, `hass.async_block_till_done()` after each push, `er.async_get(hass)` for the entity registry).

You still cannot run pytest on Windows; that's expected. Reason carefully from the HA test API, and **say in your report that CI is the verification**.

## Evidence
- The code change for item 1 (file:line) and the exact test lines changed for item 2, plus anything found in item 3.
- `ruff` and `mypy` output (both run locally).
- `git diff --stat`. Never write git state; the PM pushes to the PR branch.
- **Honesty rule:** as always.

## Standing rules
- As in M11b. Don't touch the app repo.
