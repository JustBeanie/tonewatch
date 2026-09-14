# Progress

<!-- Summary (written by the agent at stop condition) -->

M0.1–M0.5 are complete and verified locally. M0.6 has a passing Windows
spike, with Ubuntu amd64/arm64 awaiting CI. M0.7 remains the user gate because
no GitHub remote exists.

Tick a task with `[x]`, then append ` — <PR link> — <one-line note>`. Blocked tasks get a `BLOCKED: <exact question>` line underneath.

## M0: Bootstrap
- [x] **M0.1** Create the local repo layout, `LICENSE`, `README` skeleton, `.editorconfig`, `.gitattributes` (LF everywhere, `*.wav binary`) and `.gitignore`. — local — Setup, check, and pre-commit verification passed.
- [x] **M0.2** Create `backend/pyproject.toml` (uv, ruff, mypy, pytest config as above). Add `src/tonewatch/__main__.py` with `--version`. — local — Backend build, mypy, tests, and coverage passed.
- [x] **M0.3** Create `web/` with Vite React-TS, the strict tsconfig, ESLint flat config, Prettier and Vitest. Add one passing test. — local — TypeScript, ESLint, Prettier, Vitest, and 100% scaffold coverage passed.
- [x] **M0.4** Add the `justfile` and `.pre-commit-config.yaml` with all hooks. — local — Setup, check, and all-files pre-commit passed; manual CI hooks documented in ADR 0002.
- [x] **M0.5** Add `ci.yml`, `pr-title.yml`, `codeql.yml`, `renovate.json`, issue/PR templates, `CODEOWNERS`, `SECURITY.md` and `CONTRIBUTING.md`. — local — Workflows and metadata added with verified action SHAs.
- [x] **M0.6** **Spike (blocking):** verify on ubuntu, windows and ubuntu-arm CI that PyAV wheels can **encode MP3 (libmp3lame) and Opus**, and that `sounddevice` imports. — local — Windows PASS with PyAV 18.1.0/FFmpeg 60.26.102; Linux amd64/arm64 verified in CI run 34560416042 (needs apt libportaudio2).
- [x] **M0.7** 🛑 USER GATE: create the GitHub repo, apply the ruleset, enable security features and push. — https://github.com/JustBeanie/tonewatch — Created PRIVATE 2026-09-10 on user request; Dependabot on; ruleset + secret scanning unavailable on free private plan (re-run bootstrap with VISIBILITY=public at v1.0).

## M1: Domain, config and storage
- [x] **M1.1** Pydantic models: `ToneSet`, `ToneSpec`, `Source` (discriminated union: soundcard, stream, rtlsdr, file), `AlertTarget`, and cross-reference linting. — local — Model constraints, unions, references, and overlap warnings covered by unit tests.
- [x] **M1.2** `config/store.py`: load and save YAML at `$TONEWATCH_DATA/config.yaml`. — local — Safe YAML round-trip, atomic replacement, backup, crash preservation, invalid YAML, environment overrides, and add-on bootstrap tested.
- [x] **M1.3** SQLAlchemy async models `Call`, `CallToneSet`, `Recording`, `AlertAttempt`, the Alembic initial migration, ... — local — WAL SQLite repository and migration/no-drift regression verified.
- [x] **M1.4** `events.py`: typed domain events and an asyncio `EventBus` with multiple subscribers. A slow subscriber mus... — local — Typed filtering and oldest-drop bounded subscription behavior verified.

## M2: DSP engine (highest-risk area; do it thoroughly)
- [x] **M2.1** `generator.py` with every synthesis feature listed above, plus a `tonewatch-gen` CLI that writes a WAV. — local — Deterministic float32 generators and WAV CLI covered by unit tests.
- [x] **M2.2** `spectrum.py`: framing, window, FFT, parabolic interpolation, purity and level. Test frequency accuracy to ... — local — Incremental Hann FFT, log-bin interpolation, purity/level thresholds, and chunking invariance verified.
- [x] **M2.3** `segmenter.py`, with dropout tolerance and median tracking. — local — Open/extended/closed updates, dropout bridging, median frequency tracking, and smear correction verified.
- [x] **M2.4** `matcher.py`: the per-tone-set state machine, `max_gap`, cooldown and early pre-alert. — local — Per-set stream-time cooldown, early B matching, long-tone matching, excess recording, and stacked pages verified.
- [x] **M2.5** Golden scenario suite of at least 25 scenarios: clean, noisy, off-frequency, too short, too long, stacked, ... — local — 25 data-driven scenarios pass; 10-minute voice and pink-noise cases plus one-hour mixed false-positive run pass in `just test-slow`.
- [x] **M2.6** Hypothesis property tests and the benchmark (`just bench`), with the results recorded in `docs/benchmarks.md`. — local — 3 properties pass; 200-set/10-minute benchmark is 1,283× realtime.
- [x] **M2.7** `tonewatch analyze file.wav --config config.yaml` prints the detected calls and segments. This is the main ... — local — WAV normalization/resampling, table output, stable JSON schema, and CLI tests pass.

## M3: Sources and pipeline
- [x] **M3.1** `sources/base.py`: an `AudioSource` async iterator protocol, frame dataclass, and lifecycle (`open`/`close`). — local — Protocol, frozen frames, typed retry/config errors, factory, shared normalization, and cross-thread EventBus delivery tested.
- [x] **M3.2** `file.py` in realtime and fast modes. It is used by all integration tests and e2e. — local — WAV/PyAV decoding, mono 16 kHz chunks, deterministic timestamps, realtime pacing hooks, and looping tested.
- [x] **M3.3** `soundcard.py` (sounddevice callback → asyncio queue, device selection by name/index, channel select L/R/... — local — Thread-safe bounded callback queue, overflow accounting, device selection, channel handling, and `tonewatch devices` implemented/tested.
- [x] **M3.4** `stream.py`: PyAV decode of HTTP/Icecast/RTSP with exponential backoff reconnect. Test it against a local s... — local — Real PyAV Ogg/Opus decode through a threaded localhost HTTP server, forced truncated response, reconnect, monotonic time, and discontinuity flag tested.
- [x] **M3.5** `rtlsdr.py`: an `rtl_fm` subprocess with frequency, gain, ppm and squelch, reading s16le from stdout, resta... — local — Real Python fake `rtl_fm` subprocess records argv, runs twice after exit, verifies 1 kHz PCM, shell-free execution, and reaping.
- [x] **M3.6** `pipeline/channel.py` (source → ringbuffer → DSP → recorder) and `supervisor.py`, which runs N channe... — local — Concurrent channels, restart/backoff/isolation, call grouping, persistence, and generated-WAV SQLite integration verified.
- [x] **M3.7** `watchdog.py`: no frames for more than 10 s, flatline (RMS < −80 dBFS) for more than N min, clipping rati... — local — Transition-only health events, hysteresis, clipping/no-data/flatline/disconnect checks, and injected-clock tests verified.

## M4: Recording
- [x] **M4.1** Ring buffer pre-roll, then post-roll with silence early-stop and the max cap. — local — CallRecorder policy aggregation, cap/silence decisions, and pre-roll covered by focused tests.
- [x] **M4.2** Tonal-segment trimming and stacked-page merge. — local — Stream-time guarded span removal, join fades, and unioned stacked-call policies implemented and tested.
- [x] **M4.3** `encoder.py`: MP3 plus optional Opus, with metadata tags (tone set names, timestamp). Files go to `recordings/YYYY/MM/DD/<call_id>.<ext>`. — local — Atomic PyAV MP3/Opus output, metadata, persistence subscriber, and lifecycle events verified.
- [x] **M4.4** `retention.py`: max age, max total size and max count, run by a daily job. — local — Safe retention enforcement, escape refusal, pruning, injectable daily loop, and supervisor startup task verified.

## M5: API
- [x] **M5.1** FastAPI app factory, lifespan starting the supervisor, structlog JSON logs, and `/healthz` plus `/readyz`. — local — Lifespan migration/config/supervisor lifecycle, request IDs, safe errors, security headers, and health probes implemented and integration-tested.
- [x] **M5.2** Auth: a bearer API token generated on first run and stored in the data dir, with an optional UI password. — local — URL-safe owner-only token, scrypt UI sessions, ingress trust, CSRF, throttling, and CLI show/rotate implemented and tested.
- [x] **M5.3** REST: CRUD for tone sets, sources and alert targets (persisted to YAML and hot-applied); calls list and det... — local — Authenticated CRUD, live reload, calls/recordings/analyze/devices/test endpoints, range/path protections, and hostile-input tests implemented.
- [x] **M5.4** WebSocket `/api/ws`: domain events, per-channel levels, and spectrum at 5 Hz when a client subscribes. — local — Authenticated topic hub, bounded priority queues, heartbeat, connection cap, channel telemetry gate, and cleanup implemented; proving tests in `test_m5b_live_api.py`.
- [x] **M5.5** `zeroconf.py` advertises `_tonewatch._tcp`. `supervisor.py` posts Supervisor discovery (`/discovery`, servi... — local — Async mDNS advertisement, stable instance ID, add-on Supervisor registration/retry, and non-fatal startup integration implemented.
- [x] **M5.6** `openapi.json` is exported to `web/src/api/generated` via `just gen-api`, with a CI drift check. — local — Deterministic OpenAPI and Pydantic-derived WebSocket generators, committed artifacts, local drift recipe, and CI job implemented.

## M6: Web UI
- [x] **M6.1** App shell, auth, ingress-aware base path (`base: './'`) and a light/dark theme. — local — Implemented and covered by the M6a Vitest suite; api-drift PM-verified.
- [x] **M6.2** Dashboard: live call feed, channel levels and feed health. — local — Implemented and covered by `dashboard shows live call from ws event`, `level meter is accessible`, and health/level tests.
- [x] **M6.3** Calls: a list with filters and a detail view with an audio player, matched tone sets and alert attempt resu... — local — Implemented and covered by `calls filters sync to url` and `call detail plays api-provided recording url`.
- [x] **M6.4** Tone sets: a CRUD form with validation, a "test" button, and import from legacy `tones.cfg` files (M8.x importer). — local — Implemented and covered by the named validation, 422, 409, test, and accessibility tests (import waits on M8.4).
- [x] **M6.5** Frequency counter / spectrum: canvas plot, dominant frequency, pause/resume, capture tone and topic cleanup. — local — `spectrum subscribes and unsubscribes on unmount`, `capture tone prefills toneset form`, `spectrum live region throttled to 1 per second`.
- [x] **M6.6** Sources: device picker, stream URL, and RTL-SDR parameters, with live level preview. — local — source CRUD form, MHz-to-Hz conversion, validation, device and level tests.
- [x] **M6.7** Alerts configuration with a "send test" button, and Settings for retention, auth and MQTT. — local — write-only webhook secret, script warning/403, send test and read-only settings tests.
- [x] **M6.8** Analyze: upload a WAV and view the segment timeline. This is the debugging page. — local — 20 MB client gate, progress, 413/415 handling, SVG timeline and detections tests.
- [x] **M6.9** Playwright e2e: create a tone set, file source plays the fixture, the call appears in under 10 s, and the audio plays. — local — Real single-port backend run: 4 Playwright specs passed with Chrome.

## M7: Alerts
- [x] **M7.1** `dispatcher.py` subscribes to events and maps tone sets to targets. It adds per-target retry with exponenti... — local — 37 M7 tests cover dedupe, retries, concurrency, test payloads, and attempt rows.
- [x] **M7.2** `mqtt.py` (aiomqtt): LWT availability topic, `tonewatch/<instance>/call` and `.../health/<channel>` topics,... — local — MQTT publisher, Supervisor credential fallback, bounded outbox; M7-fix: real amqtt broker test `test_mqtt_real_broker_call_health_lwt_and_discovery` (skipped on win32, PENDING Linux CI) and Windows selector-loop client thread.
- [x] **M7.3** `ha_discovery.py`: a device per instance, an `event` entity per tone set (event_types `pre_alert`, `recordi... — local — Stable discovery payloads, availability, and retained deletion clears covered.
- [x] **M7.4** `webhook.py`: JSON POST with an HMAC-SHA256 signature header, timeout, and an optional multipart audio atta... — local — URL safety, pinned DNS, redirects, signatures, response cap, attachment root/cap, and secret redaction covered.
- [x] **M7.5** `script.py`: off by default. It uses an allowlisted executable path and an argv list with `{call_id}`/`{rec... — local — Allowlist, symlink escape, argv injection, env isolation, bounded output, and timeout reap covered.

## W1: Wiring

- [x] **W1a.1** Wire one settings-backed `CallRecorder` per production channel and reset it between calls. — local — `test_app_records_call_end_to_end`, `test_source_eof_during_post_roll_finalizes_recording`, `test_sequential_calls_on_one_channel_produce_two_recordings`, `test_toneset_created_via_api_detects_on_running_channel`, `test_recorder_per_frame_cost_is_constant_after_call_start`, `test_shutdown_slow_encoder_still_leaves_consistent_recording_state`, `test_shutdown_never_cancels_inflight_persistence_commit`, and `test_startup_reconciles_orphan_recording_files`.
- [x] **W1a.2** Inject the real `Watchdog` into each production channel. — local — `test_healthy_feed_stays_healthy_through_supervisor`.
- [x] **W1a.3** Start retention from the application lifespan with the configured root and policy. — local — `test_retention_runs_in_app_lifespan`.
- [x] **W1a.4** Finish recordings on EOF, recorder stop, source error, and bounded shutdown cancellation. — local — `test_source_eof_during_post_roll_finalizes_recording`, `test_channel_finalizes_recording_on_source_error`, `test_channel_cancel_ends_task_during_finish`, `test_shutdown_slow_encoder_still_leaves_consistent_recording_state`, `test_shutdown_never_cancels_inflight_persistence_commit`, `test_persistence_stop_while_busy_leaves_no_pending_tasks`, `test_app_shutdown_leaves_no_tonewatch_tasks`, and `test_startup_reconciles_orphan_recording_files`; policy is recorded in ADR 0006.
- [x] **W1a.5** Replace the recorder hook fallback with the typed five argument protocol and propagate hook errors. — local — `test_recorder_hook_type_error_propagates`.
- [x] **W1a.6** Resolve persisted recordings to authenticated API URLs before real webhook `recording_ready` delivery. — local — `test_webhook_alert_fires_for_real_recorded_call`, `test_recording_ready_alert_waits_for_persisted_row_without_polling`, `test_external_alert_payloads_never_contain_filesystem_paths`, and `test_dispatcher_does_not_swallow_session_errors`.
- [x] **W1b.1** Serve the built SPA from the backend with API-safe history fallback, CSP, cache headers, and traversal protection. — local — SPA integration tests pass.
- [x] **W1b.2** Make root and trusted-ingress deep links resolve their assets without harness HTML injection. — local — Base-path ADR and backend deep-link/ingress tests pass.
- [x] **W1b.3** Replace the proxy e2e with Playwright’s real single-port app, fixture generator, UI flows, WebSocket check, CI job, and teardown check. — local — `just e2e` reports 4 passed (3.4m), exit code 0.

## M8: Docker, release and importer
- [x] **M8.1** Multi-stage `Dockerfile` — `e57ec0d` — PM-verified on CI run 34681525844: amd64 + arm64 build, image 347,219,215 bytes (< 350 MB budget), trivy clean, smoke (in-image imports, UID 10001, read-only root, PyAV TLS) green.
- [x] **M8.2** Compose examples for soundcard (`/dev/snd`), stream, and RTL-SDR (`/dev/bus/usb`) with S5 hardening — `e57ec0d` — `compose-config` CI job validates all three files and the published 8099 port; device access under hardening remains a HIL checklist item.
- [x] **M8.3** Multi-arch Docker CI and release workflows with signing, SBOM, provenance, and Trivy — `e57ec0d` — Docker (all 7 jobs incl. e2e-container 4/4), CI (incl. runtime-closure) and Security (8 jobs) green on runs 34681525844/34681525861/34681525845. Release publish path (GHCR, cosign, SBOM, provenance) runs only on a published release; release-please PR creation awaits a user repo-setting decision.
- [x] **M8.4** `importers/tones_cfg.py` — PM review passed (fix3); host ci-local green — Clean-room preview/apply importer with CLI/API/UI flows, pure-ASGI body limit (no truncated apply on oversized streams), synthetic CRLF/missing-tolerance fixtures and private-fixture structural test.

## M9: Windows native
- [x] **M9.1** PyInstaller onedir spec bundles the Docker-equivalent web UI staging, sounddevice PortAudio data, PyAV DLLs, certifi, migrations, and SQLAlchemy/aiosqlite imports — local — CI green on GitHub (250221e); local build and frozen smoke pass.
- [x] **M9.2** `tonewatch service install|uninstall|start|stop|status` uses a pywin32 wrapper with graceful lifespan shutdown and an ADR — local — CI green on GitHub (250221e); fake-manager and shutdown seam tests pass.
- [x] **M9.3** `windows.yml` builds, smoke-tests, exercises the service lifecycle and schannel HTTPS, and uploads the zip — local — CI green on GitHub (250221e); workflow lint and local frozen smoke pass.

## M10: HA add-on (in `JustBeanie/ha-addons`)
- [ ] **M10.1** `tonewatch/config.yaml` settings:
- [~] **M10.2** **PENDING-HIL** — App-side add-on mode fetches MQTT credentials from Supervisor at connect time, writes recordings to `/media/tonewatch`, and posts discovery; real Home Assistant verification remains in `docs/hil-checklist.md`.
- [ ] **M10.3** Add `DOCS.md`, `CHANGELOG.md`, icon/logo and `translations/en.yaml`. Run `frenck/action-addon-linter` in th...

## M11: HA custom integration (`JustBeanie/ha-tonewatch`)
- [ ] **M11.1** Scaffold `custom_components/tonewatch/` (manifest with `zeroconf: ["_tonewatch._tcp.local."]`, `config_flow...
- [ ] **M11.2** Config flow supporting user entry (host, port, token), `async_step_zeroconf`, `async_step_hassio` (Supervis...
- [ ] **M11.3** `api.py` WebSocket client using HA's aiohttp session, with reconnect/backoff and a `DataUpdateCoordinator` ...
- [ ] **M11.4** Entities:
- [ ] **M11.5** `media_source.py` browses calls by date and resolves to authenticated recording URLs proxied through HA, so...
- [ ] **M11.6** `diagnostics.py` (token redacted), `strings.json`/translations, and repairs for app/integration version mis...
- [ ] **M11.7** Blueprints:
- [ ] **M11.8** CI: hassfest, `hacs/action`, ruff, mypy and pytest. Aim for HA integration quality scale Silver rules.

## M13: Tone auto-discovery (added 2026-09-12 at user request)
- [x] **M13.1** `dsp/discovery.py`: unmatched tone-sequence candidates (two-tone, long tone, N-tone) per channel, suppressed when any tone set matched. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.2** Clustering within `tol_pct`, `DiscoveredTone` storage + migration, caps and dismiss/promote status. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.3** Optional evidence clip per cluster (tones + up to 15 s), counted by retention. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.4** API + WS: list, promote to a pre-filled tone-set draft, dismiss, delete, clip download, `tone_discovered` event. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.5** Web "Discovered tones" page with clip player, Create tone set, Dismiss, and a dashboard badge. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.6** Opt-in notifications: webhook/MQTT/HA `tone_discovered`, and the M11 "last discovered tone" sensor. — PM review passed (M13-fix, M13-rebase); host ci-local green.
- [x] **M13.7** Settings (enabled, clip, durations, per-source opt-out) and `tonewatch analyze --discover`. — PM review passed (M13-fix, M13-rebase); host ci-local green.

## M14: Live audio restream (added 2026-09-12 at user request)
- [ ] **M14.1** `streaming/live.py` LiveHub: per-source fan-out, encoder only while listeners exist, bounded per-listener queues, squelch gate. — brief M14a
- [ ] **M14.2** Signed live URL + `live.mp3` endpoint, listener caps, token never logged. — brief M14a
- [ ] **M14.3** `live_stream` settings (off by default), per-source switch, audit. — brief M14a
- [ ] **M14.4** Web UI: Listen live, listener count, copy player URL, disclaimer.
- [ ] **M14.5** ha-tonewatch: media_source Live folder, `tonewatch.play_live`, blueprint (after M11.5).
- [ ] **M14.6** Threat model, ASVS rows and "Listen live" docs page. — brief M14a

## M15: Squelch (added 2026-09-12 at user request)
- [ ] **M15.1** `dsp/squelch.py`: level and noise-floor modes, hysteresis, attack, hang. — brief M15a
- [ ] **M15.2** `SourceBase.squelch`, legacy rtlsdr integer → `rtl_fm_squelch`, watchdog expects squelched silence. — brief M15a
- [ ] **M15.3** Pipeline state, `SquelchChanged`, WS `squelch_open`, optional `record.stop_on_squelch`; never gates detection. — brief M15a
- [ ] **M15.4** MQTT/HA activity binary_sensor and `last_activity_at`. — brief M15a
- [ ] **M15.5** Web UI squelch controls, meter lines, "Set from noise floor".
- [ ] **M15.6** Auto squelch: long-window floor/spread thresholds, calibrating fail-open, stuck-open and chatter flags (after M15a).
- [ ] **M15.7** Calibrate endpoint with suggested thresholds; effective-threshold diagnostics in status/WS.

## M16: Agencies and map (added 2026-09-12 at user request)
- [ ] **M16.1** `Agency` model (identity, address, location, stations, GeoJSON coverage, contacts), `ToneSet.agency_id`. — brief M16a
- [ ] **M16.2** Agencies CRUD + GeoJSON API, call agency snapshot (migration 0005), agency on event payloads. — brief M16a
- [ ] **M16.3** `map.tile_url` (off = no external requests), OSM preset, CSP adds only the tile origin. — brief M16a
- [ ] **M16.4** Web UI: agencies editor, Leaflet map page, live pulse, calls filter.
- [ ] **M16.5** HA: agency on MQTT events; ha-tonewatch `geo_location` per active call (after M11.4).

## M17: CAD incident correlation via icad2mqtt (added 2026-09-12 at user request)
- [ ] **M17.0** Codex improvement plan for icad2mqtt (audit, parsing, data cleaning, contract, packaging) → PM review → user. — brief M17-icad2mqtt-plan
- [ ] **M17.1** icad2mqtt structured JSON contract: retained `incidents` snapshot and `incident` new/updated/closed events. — brief M17a (icad2mqtt repo)
- [ ] **M17.2** ToneWatch CAD feed subscriber, strict schema validation, `CadIncident` table (migration 0006).
- [ ] **M17.3** Correlate incidents to calls by `Agency.cad_names` and time window; `CallEnriched` event.
- [ ] **M17.4** Unmatched CAD agencies list with "Create agency".
- [ ] **M17.5** Web UI: incident card, dashboard CAD panel, agency recent incidents.
- [ ] **M17.6** Threat model, ASVS rows, privacy (addresses follow retention, never logged).

## M18: Meshtastic notification target (added 2026-09-12 at user request)
- [ ] **M18.1** ADR 0012: transport (MQTT JSON downlink vs TCP vs serial), firmware requirements, GPL-3.0 licensing check.
- [ ] **M18.2** `MeshtasticTarget`: template, UTF-8-safe truncation, no URLs, coalescing, rate limits.
- [ ] **M18.3** Public-channel acknowledgement and amateur-radio/legal docs.
- [ ] **M18.4** API + UI: alert target form, byte-count preview, send test.
- [ ] **M18.5** Document the HA Meshtastic integration path (after M11.7).

## M19: Admin tooling (added 2026-09-13 at user request)
- [ ] **M19.1** System health page + `/api/admin/health` (per-source realtime factor, drops, disk forecast, DB size, target status, versions).
- [ ] **M19.2** Admin alerts: dead feed, disk, failing target, stuck squelch, slow DSP; rate-limited, resolved follow-ups.
- [ ] **M19.3** Alert delivery log with single-attempt audited retry.
- [ ] **M19.4** End-to-end drill: inject synthetic tones into a live channel, marked test everywhere.
- [ ] **M19.5** Config history, diff, rollback, masked export, dry-run import.
- [ ] **M19.6** Backup and restore archive (config, SQLite online backup, optional recordings).
- [ ] **M19.7** Support bundle (redacted) and in-UI log viewer.
- [ ] **M19.8** Credential management: rotate API token and live secret, change UI password, revoke sessions.
- [ ] **M19.9** Maintenance: retention dry-run/run-now, checkpoint/vacuum, orphan cleanup.
- [ ] **M19.10** Prometheus `/metrics`, off by default, token-protected.
- [ ] **M19.11** Audit log page with config diff view.
- [ ] **M19.12** Replay recent calls or WAVs against a draft config before saving.

## M12: Docs, hardening and v1.0.0
- [x] **M12.1** PM review passed; host ci-local green — Added the strict MkDocs Material site, public install and usage guides, internal-doc exclusions, offline `just docs`, and CI build; Pages publishing remains a user decision.
- [ ] **M12.2** Threat model doc: exposed API, token storage, the script hook, and webhook SSRF, with an allowlist and bloc...
- [x] **M12.3** PM review passed; host ci-local green — Added the radio recording/rebroadcasting compliance disclaimer to README and the site home page.
- [x] **M12.5** Clean-room naming scrub: rename the importer, route, CLI, fixtures and docs to neutral wording; add a pygrep gate. — local — Inventory is clean, audit migration and ASVS/threat-model evidence updated, pre-commit/just check green, and ci-local completed with four Playwright e2e tests on port 8799. PM: the proposed audit-event data migration was removed before landing (the importer never shipped in a release); the gate now also covers docs/pm.
- [ ] **M12.4** Release-please cuts v1.0.0 and the integration v1.0.0 is tagged. The user installs through HACS and runs th...

## S track: Security assurance (OWASP SAMM · DSOMM · ASVS)
- [x] **S1** *(after M1)* Baseline SAMM (15 practices) + DSOMM assessment, `docs/security/` layout, scorecard script, gaps.md. — local — Evidence-bound scorecards, deterministic generator/tests, and all-files pre-commit plus `just check` passed.
- [x] **S2** *(after S1)* DSOMM L1–2 pipeline controls: Semgrep, pip-audit, osv-scanner, zizmor, license checks, Trivy config, OpenSSF Scorecard, `just security`. — local — Security workflow, CI-only notices, dependency overrides, suppression validation, scorecard re-assessment, and all-files pre-commit passed; CI-only jobs remain PENDING-CI for PM observation.
- [x] **S3** *(after M5)* STRIDE threat model (Threat Dragon); replaces M12.2. — 9ea239a (review S3-20260911-154139 pass); since extended through TM-030 by M8.4/M10a/M13.
- [x] **S4** *(after M7)* ASVS 5.0 L2 code audit with regression tests for every fix. — local — ASVS source pinned, 253 tests pass, security/pre-commit/API-drift gates pass, and S4 threats are mitigated or documented as accepted.
- [x] **S5** *(after M8)* ZAP baseline/API DAST in e2e + container hardening (read-only fs, cap_drop, no-new-privileges). — `d3643d5`, `20d70e3`, `9b2e808` — Docker run 34687274921 green: zap-baseline and zap-api-scan exit 0, zero 5xx, FAIL-NEW 0 / WARN-NEW 0; the first real scan found and fixed a login 500 plus CSP/header gaps.
- [ ] **S6** *(after M11)* HA integration and add-on security review.
- [ ] **S7** *(before M12.4)* Final SAMM + DSOMM re-assessment. 🛑 USER GATE: accepted-risk sign-off.
