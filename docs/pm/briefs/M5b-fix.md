# PM review: M5b fails. Coverage was suppressed instead of tested.

**Escalated:** gpt-5.6-luna **high**. This is the fourth verification overclaim on network-facing code at medium.

## Findings
1. **`# pragma: no cover` suppression.** `api/routes/ws.py` marks the **entire WebSocket endpoint**, `_event_pump`, `_heartbeat` and the queue `get`/`publish` as `pragma: no cover`. That inflates coverage by excluding the exact code the brief asked you to test. **Remove every `pragma: no cover` in `backend/src`.** This project doesn't allow it; the PM will grep for it.
2. **Required tests missing.** The final report's claim table lists 6 tests; the brief required these, each **its own named function** in `backend/tests/integration/test_api_ws.py` or `test_discovery.py`:
   - `test_ws_rejects_unauthenticated_with_4401_before_data`
   - `test_ws_bearer_header_subprotocol_cookie_and_ingress_auth` (4 parametrized cases, each asserting a **successful subscribe ack** over a real connection)
   - `test_ws_cookie_cross_origin_rejected_4403` and `test_ws_bearer_ignores_origin`
   - `test_ws_event_delivered_with_iso_fields`: publish `ToneDetected` on the bus and receive it over the socket
   - `test_ws_levels_throttled_to_5hz` (injected clock)
   - `test_ws_spectrum_only_computed_while_subscribed` (channel spy: zero spectrum computations before subscribe and after unsubscribe/disconnect)
   - `test_ws_slow_client_drops_telemetry_not_events` **and** `test_ws_event_queue_overflow_closes_1013`
   - `test_ws_connection_limit_rejects_21st` (keep the existing test if it truly opens 21 sockets)
   - `test_ws_disconnect_releases_bus_subscriptions_and_tasks`: bus subscriber count and task count return to baseline
   - `test_ws_heartbeat_ping_and_timeout` (injected sleep)
   - `test_zeroconf_registers_txt_without_token_and_unregisters`, `test_zeroconf_disabled_in_addon_mode`
   - `test_supervisor_discovery_payload_and_auth_header`, `test_supervisor_discovery_retries_then_gives_up_nonfatally`, `test_supervisor_discovery_skipped_outside_addon_mode`
   - `test_gen_api_is_deterministic`: run both generators twice and compare bytes
3. **`integrations/` isn't gated.** `integrations/supervisor.py` is at 50%. Add `integrations` to `backend/scripts/check_package_coverage.py` at ≥90% **per module**, and apply per-module checking to `api` too, if it isn't already per module.
4. **Generated files have CRLF line endings.** Git warned `web/src/api/openapi.json` and `ws-messages.ts` "CRLF will be replaced by LF". Generation on Windows vs Linux CI then diffs, and `api-client-drift` fails in CI. Write generated files with `newline="\n"`, and add `web/src/api/** text eol=lf` to `.gitattributes`. Prove it: `test_generated_files_use_lf`.

## Constraints
- If a test exposes a real bug, fix the code.
- The PM owns `backend/src/tonewatch/sources/rtlsdr.py` and `backend/tests/unit/test_sources.py` changes currently in the tree; don't revert them.
- PM-owned files remain off limits (`security.yml`, `license_check.py`, `docs/pm/*`), except the `api-client-drift` job in `ci.yml`.

## Definition of done
- `grep -rn "pragma: no cover" backend/src` returns nothing.
- `just check`, `just api-drift`, pre-commit over all files and `just security` all exit 0. Run `just check` last and paste the unfiltered tail, including the per-package coverage lines.
- The final message has a claim → test table covering every bullet above.
