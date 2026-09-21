# Brief: M11c — M11.5 media source, M11.6 diagnostics and repairs, M11.7 blueprints (ha-tonewatch)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11c-media`** (the PM created it on top of the entities work; it is clean).
**Git:** never write git state. The PM commits, pushes and opens the PR.
**You cannot run pytest on Windows** (HA imports Unix-only `fcntl`). Write the tests carefully by reading the existing ones; the PM pushes and GitHub CI on Linux is the verification. Say so in your report; never claim tests pass.

## Read first
- In this repo: `custom_components/tonewatch/` (`api.py` coordinator, `entity.py`, `event.py`, `sensor.py`, `binary_sensor.py`, `switch.py`, `button.py`, `const.py`, `manifest.json`, `strings.json`, `translations/`) and `tests/`, especially how `tests/test_entities.py` drives setup and resolves entity ids from the registry.
- In the app repo `C:\Users\beanie\Documents\Proj\tonewatch` (read-only):
  - `backend/src/tonewatch/api/routes/calls.py` (list and detail shapes, filters, pagination) and `api/routes/recordings.py` (Range support, auth, content types)
  - `api/auth.py` for how the bearer token is accepted
  - `PLAN.md` M11.5, M11.6 and M11.7

## Required
1. **`media_source.py` (M11.5).**
   - Browse calls by date: a root folder, then year/month/day folders, then one item per recording, titled with the time, the tone set names and the duration.
   - Resolve an item to a **playable media URL proxied through Home Assistant**, so the ToneWatch API token never reaches the browser. Use HA's authenticated proxy pattern (`async_get_media_source`, `PlayMedia`, and a `HomeAssistantView` or the http proxy helper). If you use a view, it must require HA auth, stream the upstream response including Range headers, and never log the token.
   - Paginate sensibly and cap what a single browse level returns.
   - The recording URL join must reuse the entity helper you already have; no duplicated `recordings/` segment.
2. **`diagnostics.py` (M11.6).**
   - Config entry diagnostics with the API token, any password and the live secret **redacted** (`async_redact_data`).
   - Include the entry data (redacted), the coordinator connection state, the last error, the number of tone sets and sources, and the app version.
   - **Repairs:** raise an `issue_registry` issue when the app's version is older than the integration's minimum supported version, or when the WebSocket has been disconnected for more than five minutes, with a translated title and description. Clear each issue when it resolves.
3. **Blueprints (M11.7).** Under `blueprints/automation/tonewatch/`:
   - `play_dispatch_audio.yaml`: on a chosen tone set's `event` entity firing `recording_ready`, play the recording on a chosen `media_player`.
   - `notify_with_audio.yaml`: on the same trigger, send a mobile notification with the recording attached (iOS `attachment`) and documented Android behaviour (a link; verify what Android supports and write what you verified).
   - Both must use selectors, have translated descriptions, and be listed in the README with install instructions.
4. **README:** document the media source, diagnostics, repairs and both blueprints.

## Mandatory tests (write first; show each failing line)
- **A. Media source:** browsing the root lists date folders from a fixture call set; browsing a day lists its recordings; resolving returns a proxied URL; an unknown id raises `Unresolvable`.
- **B. Proxy auth:** the proxy view rejects unauthenticated HA requests, forwards Range headers, and the ToneWatch token appears in **no** response header or body, and in no log (`caplog`).
- **C. Diagnostics:** the dump contains no token, password or live secret (scan the whole serialized payload for the fixture values), and includes the connection state.
- **D. Repairs:** an old app version raises the issue and a matching version clears it; a long disconnect raises the issue and a reconnect clears it.
- **E. Blueprints:** both YAML files load with HA's blueprint schema (`homeassistant.components.blueprint`), have unique inputs and no undefined placeholders.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with the code under test (file:line). Mark clearly that pytest was not run locally.
- `ruff` and `mypy` output (both run on Windows). `git diff --stat`.
- The repo's coverage gate is 90 %: say which new code paths your tests cover, since CI enforces it.
- **Honesty rule:** as always. Never weaken an assertion or delete state by hand to make a test pass.

## Standing rules
- Never edit `docs/pm/**` or the app repo. No new runtime dependencies beyond what HA ships. Keep HA quality-scale Silver in mind.
