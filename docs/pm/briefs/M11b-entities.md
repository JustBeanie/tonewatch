# Brief: M11b — M11.4 entities and the `tonewatch_detected` bus event (ha-tonewatch)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch` (repo `JustBeanie/ha-tonewatch`, branch `main`, clean). **This is the integration repo, not the ToneWatch app repo.**
**Git:** never write git state (no commit, branch, push or `git add`). The PM commits and pushes.

## Read first
- In **this** repo: `custom_components/tonewatch/` (`__init__.py`, `api.py` with `ToneWatchCoordinator`, `config_flow.py`, `const.py`, `manifest.json`, `strings.json`, `translations/`), `tests/` (`conftest.py`, `test_api.py`, `test_config_flow.py`), `justfile` and the CI workflow.
- In the app repo `C:\Users\beanie\Documents\Proj\tonewatch` (read-only reference; never edit it):
  - `backend/src/tonewatch/api/routes/ws.py` and `backend/src/tonewatch/api/ws_models.py` for the exact WebSocket message shapes and topics
  - `backend/src/tonewatch/events.py` for the domain events (`ToneDetected`, `RecordingReady`, `FeedHealthChanged`, `CallClosed`, `CallEnriched`)
  - `backend/src/tonewatch/api/routes/admin.py` `health()` for feed health, and `api/routes/config.py` for tone sets (`GET /api/tonesets`, `PUT /api/tonesets/{id}`) and `POST /api/tonesets/{id}/test`
  - the recording URL shape in `api/routes/recordings.py`
- `PLAN.md` M11.4 in the app repo.

## Required (this slice: entities and the bus event only)
Everything is **push-driven** from the coordinator. No polling except an initial REST fetch on setup.

1. **Platforms:** `event`, `sensor`, `binary_sensor`, `switch`, `button`, listed in `__init__.py` `PLATFORMS` and forwarded on setup, unloaded cleanly on unload.
2. **Entities**, all under one device per ToneWatch instance (identified by the instance id from the config entry), with translated names and stable unique ids (`{instance_id}_{kind}_{id}`):
   - **`event` per tone set:** event types `pre_alert` and `recording_ready`. Attributes carry `call_id`, `toneset_id`, `recording_url` (absolute, built from the entry host/port) and `test`/`drill` flags. Tone sets come from the initial REST fetch and follow config changes.
   - **`sensor.last_call`:** the most recent call's timestamp as the state (`device_class: timestamp`), with tone set names, source and call id as attributes.
   - **`binary_sensor` call active:** on between a detection and the call closing.
   - **`binary_sensor` feed healthy, per source:** from `FeedHealthChanged` and the initial health fetch, `device_class: connectivity`.
   - **`switch` per tone set:** enabled state, written through `PUT /api/tonesets/{id}`; optimistic update then confirm, reverting on failure.
   - **`button` per tone set:** fires `POST /api/tonesets/{id}/test`.
3. **Bus event:** fire `tonewatch_detected` on the HA bus for each detection, carrying `call_id`, `toneset_id`, `source_id`, `recording_url`, `test` and `drill`. Document it in the README.
4. **Availability:** every entity is unavailable while the WebSocket is disconnected, and recovers on reconnect. **No entity may ever expose the API token**, including in attributes or the recording URL (the URL carries no token; HA fetches it with the auth header, and M11.5 will proxy it).

## Mandatory tests (write first; show each failing line)
Use `pytest-homeassistant-custom-component`, as the existing tests do.
- **A.** Setup from a mocked coordinator creates exactly the expected entities for a two-tone-set, two-source fixture, with their unique ids; unload removes them.
- **B.** A pushed `ToneDetected` frame fires the tone set's `event` entity with `pre_alert`, sets call-active on, updates `sensor.last_call`, and fires exactly one `tonewatch_detected` bus event with the right data. A `RecordingReady` frame fires `recording_ready` with an absolute `recording_url`.
- **C.** `FeedHealthChanged` flips the matching feed binary sensor only.
- **D.** The switch writes through the API and reverts on a failed write (assert the API call and the final state). The button posts the test endpoint.
- **E.** A disconnect marks entities unavailable, and a reconnect restores them.
- **F.** No entity attribute, and no log line during these tests (`caplog`), contains the fixture API token.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` green in this repo (ruff, mypy strict, pytest with its 90 % coverage gate), with the pasted summary lines. `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without evidence; never claim green without the pasted output.

## Standing rules
- Never edit `docs/pm/**` or anything in the app repo. No new runtime dependencies. Never weaken a gate.
- Keep HA quality-scale Silver in mind: translated names, unique ids, availability, no blocking I/O in the event loop, and no `async_update` polling.
- Nothing else is running in this repo; you own the checkout.
