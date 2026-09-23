# Brief: M11e — M14.5 live audio in HA and M16.5 agency data on events (ha-tonewatch)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11e-live-agency`** (the PM creates it from `main` after M11d lands; it will be clean).
**Git:** never write git state. The PM commits, pushes and opens the PR.
**You cannot run pytest on Windows** (HA imports Unix-only `fcntl`). Write tests by reading the existing ones; CI on Linux verifies. Never claim pytest or coverage results you did not run.

## Read first
- In this repo: `media_source.py` (browse, resolve and the proxy view), `urls.py`, `api.py`, `entity.py`, `event.py`, `sensor.py`, `binary_sensor.py`, `tests/`.
- In the app repo `C:\Users\beanie\Documents\Proj\tonewatch` (read-only):
  - `backend/src/tonewatch/streaming/live.py` and `api/routes/live.py`: the live MP3 restream, `POST /api/sources/{id}/live-url` and its **signed, expiring** URL (`expires_at` is ISO 8601), plus how listeners are counted and released
  - `api/routes/admin.py` `health()` for `live_stream` state, and `config/models.py` `LiveStreamConfig` / `live_stream_enabled` per source
  - agency data: `config/models.py` `Agency`, the call agency snapshot (`agency_id`, `agency_name`, `agency_kind`), `api/routes/agencies.py` (including the GeoJSON), and how `alerts/mqtt.py` and the WS events carry agency fields
  - `PLAN.md` M14.5 and M16.5

## Required
### M14.5 live audio
1. **Media source "Live" folder:** a top-level `Live` folder beside the date folders, listing one item per source whose live stream is enabled. Resolving an item returns a **proxied** URL (through the existing HA-authenticated view pattern), never a signed app URL, so the token and the signature never reach the browser.
   - The integration fetches a fresh signed URL per playback start, and refreshes it when it expires mid-stream, or documents clearly that playback ends at expiry and why.
   - Releasing: when HA stops playing, the upstream listener must be released. Prove that the upstream connection is closed when the client disconnects.
2. **Service `tonewatch.play_live`:** fields `source_id` and `media_player` (entity selector). It resolves the live media and calls `media_player.play_media`. Register it in `services.yaml` with translated names and descriptions, and raise `HomeAssistantError` on failure (unknown source, live disabled, upstream error).
3. **Blueprint** `listen_live.yaml`: on a chosen trigger, play a chosen source live on a chosen media player.

### M16.5 agency data
4. **Agency on events and entities:** the `tonewatch_detected` bus event and the `event` entities' attributes carry `agency_id`, `agency_name` and `agency_kind` when the call has them. Keep the existing attribute names stable.
5. **`geo_location` per active call** (only when the call's agency has coordinates): create a `geo_location` entity while a call is active and remove it when the call closes, with the agency name as the source and the distance from home computed by HA. No incident addresses, ever: only the agency's own coordinates.
6. **README:** document the Live folder, the service, the blueprint, the agency attributes and the geo_location entity, including that addresses are never published to HA.

## Mandatory tests (write first)
- **A.** The Live folder lists only live-enabled sources; resolving returns a proxied URL; an unknown or disabled source raises `Unresolvable`.
- **B.** The proxy releases the upstream listener when the HA client disconnects (assert the upstream response was closed), and the signed URL never appears in a response body, header or log.
- **C.** `tonewatch.play_live` calls `media_player.play_media` with the resolved URL, and raises `HomeAssistantError` for an unknown source, a live-disabled source and an upstream failure.
- **D.** Agency fields appear on the bus event and the event entity when present, and are absent (not `None` strings) when the call has no agency.
- **E.** A `geo_location` entity appears for an active call with agency coordinates and disappears when the call closes; no address string from the fixture appears in any attribute (scan the whole state).
- **F.** The blueprint loads against HA's blueprint schema.

## Evidence (the report is rejected without it)
- A table mapping each test to its letter with the code under test (file:line).
- `ruff` and `mypy` output, and `git diff --stat`. State plainly that pytest was not run locally.
- Coverage must stay at or above the repo's gate; say which new paths your tests cover.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or the app repo. No new runtime dependencies. Keep Silver-scale rules intact: unique ids, availability, translations, `HomeAssistantError` from actions, `PARALLEL_UPDATES`.
