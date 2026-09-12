# ToneWatch STRIDE threat model

Open `tonewatch.json` in [OWASP Threat Dragon](https://threatdragon.org/): use **Open Model**, choose the JSON file, and select the `ToneWatch data flow` diagram. The file is Threat Dragon v2 JSON with one STRIDE diagram; the inventory below is the authoritative evidence ledger.

## Scope and assumptions

This review covers the M0-M7 implementation as of 2026-09-11. ToneWatch is self-hosted for one household or department, with Home Assistant as the primary deployment. LAN traffic is not assumed confidential unless TLS is supplied by the deployment or HA ingress. Host filesystem permissions, container isolation, and Supervisor policy are deployment responsibilities unless explicitly evidenced here.

The stream SSRF finding is concrete: a user who can write a `StreamSource` can set `url` to an internal HTTP endpoint such as `http://169.254.169.254/`; `StreamAudioSource` passes the URL directly to `av.open` in `backend/src/tonewatch/sources/stream.py:18-23`, and the config model only validates URL syntax. Minimal reproduction: save a config containing `{"type":"stream","url":"http://169.254.169.254/latest/meta-data/"}` (or an internal service URL), start the channel, and observe the application host/container making the request. No network allowlist or private-address rejection exists today.

## Threat inventory

Evidence uses repository-relative `path:line`; “no proving test” is intentional for `open`, `partial`, and planned rows. A mitigated row is only used where a named test function exists in `backend/tests`.

| ID | STRIDE | Element | Description | Likelihood | Impact | Status | Evidence | Owning task |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TM-001 | Spoofing | Auth middleware | A LAN client spoofs the HA ingress header to bypass auth. | med | high | mitigated | `backend/src/tonewatch/api/auth.py:100`; `test_ingress_trusted_only_in_addon_mode_from_supervisor_ip` | M5 |
| TM-002 | Spoofing | api_token file | A host reader steals the bearer token from the data directory. | med | high | partial | `backend/src/tonewatch/api/auth.py:25`; no proving test | S4 |
| TM-003 | Spoofing | FastAPI app (REST + WS) | A client completes a WebSocket handshake without authentication. | med | high | mitigated | `backend/src/tonewatch/api/routes/ws.py:110`; `test_ws_rejects_unauthenticated_with_4401_before_data` | M5 |
| TM-004 | Spoofing | Zeroconf responder | A rogue `_tonewatch._tcp` service lures future HA integration discovery and credential submission. | med | high | planned | `backend/src/tonewatch/integrations/zeroconf.py:43`; no proving test | M11 |
| TM-005 | Tampering | config.yaml | Concurrent config writes can race backups or overwrite a newer configuration. | med | med | partial | `backend/src/tonewatch/config/store.py:41`; no proving test | S4 |
| TM-006 | Tampering | Recordings directory | A recording database path or download identifier is used for traversal outside the recording root. | low | high | mitigated | `backend/src/tonewatch/api/routes/recordings.py:20`; `test_recording_path_outside_root_is_refused` | M5 |
| TM-007 | Tampering | Recorder / encoder | Malicious WAV/stream media reaches PyAV/FFmpeg parser code and may exploit a decoder vulnerability. | med | high | partial | `backend/src/tonewatch/sources/stream.py:20`; no proving test | S4 |
| TM-008 | Tampering | rtl_fm subprocess | Config values inject shell syntax or alter the intended RTL command. | low | high | mitigated | `backend/src/tonewatch/sources/rtlsdr.py:96`; `test_rtlsdr_fake_process_restarts_without_shell` | M5 |
| TM-009 | Repudiation | config.yaml | Config changes have no audit record identifying actor, time, or before/after values. | med | med | open | `backend/src/tonewatch/config/store.py:41`; no proving test | S4 |
| TM-010 | Repudiation | FastAPI app (REST + WS) | Test-page triggers are persisted as events without caller identity or audit trail. | med | low | partial | `backend/src/tonewatch/api/routes/config.py:125`; no proving test | S4 |
| TM-011 | Information disclosure | Logs | Passwords, tokens, cookies, or authorization data may be emitted in rendered logs. | med | high | partial | `backend/src/tonewatch/logging.py:18`; `test_secrets_never_logged` (rendered-output caveat) | S4 |
| TM-012 | Information disclosure | Recordings directory | Authenticated LAN exposure or a compromised client exposes radio recordings. | med | high | mitigated | `backend/src/tonewatch/api/routes/recordings.py:14`; `test_every_api_route_requires_auth` | M5 |
| TM-013 | Information disclosure | FastAPI app (REST + WS) | OpenAPI, Swagger, or ReDoc reveals the API surface to unauthenticated users. | low | low | mitigated | `backend/src/tonewatch/api/app.py:59`; `test_every_api_route_requires_auth` | M5 |
| TM-014 | Information disclosure | FastAPI app (REST + WS) | Exceptions reveal local paths, tracebacks, or implementation details. | med | med | mitigated | `backend/src/tonewatch/api/app.py:123`; `test_errors_do_not_leak_internals` | M5 |
| TM-015 | Information disclosure | Zeroconf responder | Zeroconf TXT records reveal more deployment metadata than intended. | med | low | partial | `backend/src/tonewatch/integrations/zeroconf.py:48`; `test_zeroconf_registers_txt_without_token_and_unregisters` | S4 |
| TM-016 | Denial of service | FastAPI app (REST + WS) | Analyze upload body exceeds memory or processing limits. | med | med | mitigated | `backend/src/tonewatch/api/app.py:32`; `test_analyze_rejects_oversize_413_while_streaming` | M5 |
| TM-017 | Denial of service | FastAPI app (REST + WS) | WebSocket clients exhaust connection slots or per-client queues. | med | med | mitigated | `backend/src/tonewatch/api/routes/ws.py:20`; `test_ws_connection_limit_rejects_21st` | M5 |
| TM-018 | Denial of service | FastAPI app (REST + WS) | Slow-loris HTTP clients hold uvicorn workers and sockets indefinitely. | med | med | open | `backend/src/tonewatch/api/app.py:87`; no proving test | S4 |
| TM-019 | Denial of service | Recorder / encoder | Decompression or long-audio input causes unbounded decode/CPU work. | med | med | mitigated | `backend/src/tonewatch/api/routes/analyze.py:25`; `test_analyze_rejects_over_10_minutes` | M5 |
| TM-020 | Denial of service | Retention job | Recordings fill the disk despite retention policy or unsafe paths. | med | high | mitigated | `backend/src/tonewatch/recording/retention.py:37`; `test_retention_deletes_oldest_and_refuses_escape` | M5 |
| TM-021 | Denial of service | Supervisor / channels | Many tone sets or channels consume CPU, memory, and bounded event queues. | med | med | partial | `backend/src/tonewatch/events.py:104`; no proving test | S4 |
| TM-022 | Denial of service | Auth middleware | Login-throttle state grows without a global bound when keyed by spoofed IPs. | med | med | open | `backend/src/tonewatch/api/auth.py:84`; no proving test | S4 |
| TM-023 | Elevation of privilege | Alert dispatcher (M7) | Script alert targets execute attacker-controlled arguments or binaries as the container user. | med | high | mitigated | `backend/src/tonewatch/alerts/script.py:52`; `test_script_executable_must_be_in_allowlist_and_not_symlink_escape` | M7 |
| TM-024 | Elevation of privilege | Container | A root container turns an application compromise into host compromise. | low | high | planned | `PLAN.md:100`; no proving test | M8 |
| TM-025 | Elevation of privilege | Supervisor discovery client | HA add-on permissions (`hassio_api`, `map: media:rw`) exceed least privilege after compromise. | low | high | planned | `backend/src/tonewatch/integrations/supervisor.py:24`; no proving test | M10 |
| TM-026 | Elevation of privilege | Alert dispatcher (M7) | Webhook targets permit SSRF to internal services or cloud metadata. | med | high | mitigated | `backend/src/tonewatch/alerts/urlsafety.py:160`; `test_urlsafety_blocks_loopback_linklocal_metadata_and_encodings` | M7 |
| TM-027 | Elevation of privilege | Network stream origin | A configured stream URL can target localhost, `169.254.169.254`, or private services (SSRF). | high | high | open | `backend/src/tonewatch/sources/stream.py:20`; no proving test | S4 |

## Accepted risks

No current finding is accepted. Planned future surfaces remain explicitly out of scope until their owning milestone implements and tests them.
