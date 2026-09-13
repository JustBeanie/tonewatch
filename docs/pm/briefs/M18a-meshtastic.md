# Brief: M18a — Meshtastic notification target (backend: M18.1–M18.3)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18a` (branch `m18a`, based on `origin/main`). **E2E port:** `TONEWATCH_E2E_PORT=8806`.

## Goal
Implement `PLAN.md` M18.1–M18.3: a Meshtastic alert target that forwards a short page summary to a Meshtastic node, which rebroadcasts it over the mesh. **The UI form (M18.4) and the HA path (M18.5) are out of scope.** Other engineers are working in parallel on live restream, squelch and agencies. Keep edits to shared files (`config/models.py`, `alerts/dispatcher.py`, the generated web client, `docs/PROGRESS.md`) small and additive.

## Required
1. **ADR spike first** (`docs/decisions/0012-meshtastic-transport.md`, AGENTS rule 7).
   - From Meshtastic's official documentation and firmware source (cite URLs and the firmware version or commit), establish exactly what an MQTT **JSON downlink** `sendtext` requires:
     - the topic shape (root topic, region, `json` path, channel name)
     - required node settings (MQTT enabled, JSON enabled, which channel must exist and have downlink enabled)
     - payload fields (`from`, `to`, `channel`, `type`, `payload`) and their types
     - the maximum text payload in bytes
   - Record any firmware versions where JSON downlink was removed or changed. If it's unsupported on current firmware, **stop and report** instead of guessing.
   - Compare the TCP API (port 4403) and serial transports. **Licensing:** the Meshtastic Python library and protobufs are GPL-3.0 and ToneWatch is Apache-2.0. State what that means for shipping (b) or (c) in the image, without legal overreach, and recommend.
   - v1 implements only the MQTT JSON downlink.
2. **Model (`config/models.py`, test-first).** Add `MeshtasticTarget` to the `AlertTarget` union:
   - **Fields:** `type: "meshtastic"`, `id`, `name`, `transport: Literal["mqtt"]`.
   - **Broker:** either inline broker settings mirroring `MqttTarget` (host/port/tls/username/password, with the password handled exactly as `MqttTarget` handles secrets) or `mqtt_target_id` referencing an existing MQTT target. Exactly one of the two, reference-checked.
   - **Mesh addressing:**
     - `root_topic` (default per the ADR)
     - `gateway_node_id`, the `!xxxxxxxx` form, validated and converted to the number the payload needs
     - `channel_index` (0–7)
     - `destination` (`"broadcast"` or a `!xxxxxxxx` node id)
   - **Message:** `template` (default e.g. `"TONE {agency_short} {toneset} {time}"`), `max_bytes` (default 200, hard cap from the ADR), `phases` (default `["pre_alert"]`).
   - **Limits:** `min_interval_s` (default 30), `max_per_hour` (default 20).
   - **Safety:** `acknowledge_public_channel: bool = False`. Validation fails for `channel_index == 0` unless it is true, with a message explaining that the default channel is readable by anyone nearby.
3. **Sender (`alerts/meshtastic.py`, test-first).**
   - **Template rendering:** the allowed fields are `{agency_short}`, `{agency}`, `{toneset}`, `{tonesets}` (comma-joined for stacked pages), `{time}` (local HH:MM), `{source}` and `{call_id_short}`.
     - M16 agencies may not have landed on your base. Fill agency fields from the tone-set name when there is no agency, and cover both cases in tests.
     - Unknown fields fail validation at config time, not at send time.
     - `{cad_type}`/`{cad_address}` are **not** added now (M17).
   - **Sanitizing:** strip control characters and collapse whitespace. **Never include URLs:** reject any template containing `http`, and scrub URL-like text from rendered values. Add a test that a tone-set name containing a URL, and a recording URL anywhere in the event, never reach the payload.
   - **Truncation:** truncate to `max_bytes` on a UTF-8 code-point boundary with a trailing `…` if it fits. Hypothesis property: never over `max_bytes`, always valid UTF-8, and the prefix is preserved.
   - **Coalescing:** stacked tone sets in the same call within the pre-alert window produce one message.
   - **Rate limiting:** apply `min_interval_s` and `max_per_hour` per target. When over the limit, send nothing and record an `AlertAttempt` with outcome `rate_limited` (add it to the existing outcome set the way `AlertAttempt` outcomes are modelled; a migration only if the column is constrained). Dispatcher retries must not bypass the limiter.
   - **Publish** with aiomqtt at QoS 1, not retained. A connection error counts as a normal failed attempt with the existing retry/backoff. Never log the broker password.
4. **Wiring.** Register it in the dispatcher, include it in `POST` alert-target "send test" (the test message is marked `TEST`), and regenerate the web client (`just gen-api`).
5. **Docs.**
   - A public docs page "Meshtastic": node settings required (from the ADR), an example config, limits, the public-channel warning, and a note that licensed amateur-radio operation forbids encryption and restricts content.
   - A threat-model entry: data sent over RF, readable by anyone holding the channel key; no URLs or tokens.
   - ASVS rows only if they apply, following the existing file conventions exactly.
6. **Tests.**
   - Model validation, including the public channel, node id formats and the broker exactly-one rule.
   - Golden payload JSON.
   - The truncation property, the URL-scrub tests, and coalescing and rate limiting.
   - An embedded-broker integration test (reuse the existing MQTT test broker fixture) asserting topic, QoS, retain flag and payload.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate: no skips, no lowered coverage, no `# type: ignore`/`noqa` without a same-line justification.
- **No new dependencies**, and in particular no Meshtastic Python package or vendored protobufs (GPL-3.0).
- Never print, log or commit anything from `backend/tests/fixtures/private/`. Use invented node ids and names.
- No legacy product naming. Never commit or push.

## Definition of done
- `just check` passes. Paste the pytest and vitest summary lines.
- `just ci-local` with `TONEWATCH_E2E_PORT=8806` passes, including security, api-drift and e2e. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- In `docs/PROGRESS.md`, M18.1–M18.3 are marked `[~] PENDING-REVIEW`, one line each.
- The final report quotes the ADR's verified downlink requirements with citations, the licensing conclusion, an invented example payload, and every changed file.
