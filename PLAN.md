# Plan: Modern ToneWatch radio notifier (working name `tonewatch`)

## Context

A legacy desktop-style radio notifier listens to scanner or radio audio, detects two-tone and long-tone fire/EMS pages, sends a pre-alert, records the dispatch audio that follows, and pushes that audio out by email, script or other channels. The goal is a clean-room rebuild on a modern stack, published on GitHub with strict linting and CI, and structured so that autonomous coding agents (ChatGPT/Codex-style, medium reasoning) can build it milestone by milestone without supervision.

Decisions already made with the user:
- **Stack:** Python backend and React/TypeScript web UI.
- **Deploy targets:** Docker on Linux/Raspberry Pi, a Home Assistant add-on, and a native Windows build.
- **Audio inputs for v1:** sound card/USB, network stream, and RTL-SDR.
- **Outputs for v1:** MQTT with HA discovery, webhook, run-script, and a direct way to get audio into Home Assistant.

The working name `tonewatch` is a placeholder. Check the name is free on GitHub, PyPI and GHCR before M0. Do not reuse any external product name, code or UI; the project must be clean-room.


---

## Answers to the open questions

### Should it be dockerized?
**Yes. Docker is the primary distribution, but not the only one.**
- **Linux/Pi:** sound cards pass through with `devices: [/dev/snd]` and RTL-SDR dongles with `/dev/bus/usb`. Build one multi-arch image (amd64 + arm64).
- **HA add-on:** reuses **the same image**. It reads `/data/options.json` when `SUPERVISOR_TOKEN` is set.
- **Windows:** Docker Desktop cannot pass a sound card or USB SDR into a Linux container, so Windows gets a **native build** (PyInstaller, WASAPI via PortAudio). A Windows Docker host can still use network-stream input.

### Can audio go straight into Home Assistant, and should an integration be made?
**Yes to both. There are three layers, built in this order:**
1. **Add-on media folder (zero code).** The add-on maps HA's `media` folder and writes recordings to `/media/tonewatch/`. They appear immediately in HA's Media browser, can be played on any `media_player`, and can be attached to notifications.
2. **MQTT discovery (M7).** This gives HA entities for anyone running plain Docker: an `event` entity per tone set, a last-call sensor, and feed-health binary sensors. Each event payload carries the recording URL. MQTT cannot carry the audio itself, only a link to it.
3. **Custom integration `ha-tonewatch` (M11, installed through HACS).** This is the proper native experience:
   - Config flow, with auto-discovery through Supervisor discovery (add-on) or zeroconf (Docker).
   - Push updates over WebSocket (no polling).
   - Event, sensor, binary_sensor, switch and button entities.
   - A **`media_source` platform** so recordings show up in the Media browser from *any* install type.
   - A `tonewatch_detected` bus event.
   - Shipped blueprints: "play dispatch audio on a speaker" and "phone notification with audio".

**Recommendation:** once the integration exists it becomes the main HA path. MQTT discovery stays for non-HA users and defaults to **off** when the integration is configured, so entities are not duplicated.

---

## Architecture

```
 AudioSource (sounddevice | PyAV stream | rtl_fm subprocess | file)
      │  float32 mono @16 kHz frames + monotonic timestamps
      ▼
 Channel pipeline (one per source, asyncio task)
   ├─ RingBuffer (pre-roll)
   ├─ Spectrum (4096-sample Hann FFT, 100 ms hop, parabolic peak interp)
   ├─ Segmenter (stable-tone segments: freq, start, duration, purity)
   ├─ Matcher (tone sets = ordered sequences of (freq ±tol, min/max dur))
   ├─ Recorder (post-roll, early-stop on silence, tone trimming, stacked pages)
   └─ Watchdog (no data / flatline / clipping / disconnect)
      │  domain events: ToneDetected, RecordingReady, FeedHealthChanged
      ▼
 EventBus ─► Dispatcher (retry, dedupe, cooldown) ─► MQTT | Webhook | Script
      │
      ├─► SQLite (SQLAlchemy 2 + Alembic): calls, recordings, alert attempts
      └─► FastAPI: REST + WebSocket (events, levels, live spectrum) ─► React UI / HA integration
```

### Key technology choices
| Area | Choice |
|---|---|
| Python | 3.13, managed by **uv** (bump to 3.14 only after verifying arm64 + Windows wheels for numpy, scipy, av, sounddevice) |
| DSP | numpy + scipy.signal |
| Audio I/O | `sounddevice` (PortAudio: ALSA/Pulse/WASAPI); `av` (PyAV) for stream decode, resampling and MP3/Opus encode; `rtl_fm` subprocess |
| API | FastAPI, uvicorn, pydantic v2, pydantic-settings |
| MQTT | `aiomqtt` |
| Discovery | `zeroconf` |
| Storage | SQLite via SQLAlchemy 2 (async), Alembic |
| Web | Node 24 LTS, pnpm 10, Vite, React 19, TypeScript strict, TanStack Query, React Router, Tailwind v4 + shadcn/ui, `openapi-typescript` generated client |
| Tests | pytest, pytest-asyncio, hypothesis, pytest-benchmark, coverage; Vitest + Testing Library; Playwright |
| Task runner | `just` (cross-platform) |

---

## Repositories

| Repo | Contents |
|---|---|
| `JustBeanie/tonewatch` | Monorepo: backend, web, Docker, Windows packaging, docs |
| `JustBeanie/ha-tonewatch` | HACS custom integration and blueprints (HACS needs its own repo) |
| `JustBeanie/ha-addons` (existing) | `tonewatch/` add-on **manifest only**, pointing at the GHCR image. This matches the existing bacnet split pattern. |

### Monorepo layout
```
tonewatch/
  AGENTS.md  PLAN.md  README.md  LICENSE (MIT)  SECURITY.md  CONTRIBUTING.md
  CODE_OF_CONDUCT.md  CHANGELOG.md  justfile  .pre-commit-config.yaml
  .editorconfig  .gitattributes  .gitignore  renovate.json
  docs/PROGRESS.md            # agent resume log; checkbox per task ID
  docs/ (mkdocs-material site)
  .github/workflows/{ci,docker,release,windows,codeql,pr-title}.yml
  .github/{ISSUE_TEMPLATE/,PULL_REQUEST_TEMPLATE.md,CODEOWNERS}
  backend/pyproject.toml  backend/uv.lock
  backend/src/tonewatch/
    __main__.py  settings.py  events.py
    config/{models.py,store.py}          # ToneSet, Source, AlertTarget; YAML load/save
    dsp/{spectrum.py,segmenter.py,matcher.py,generator.py}
    sources/{base.py,file.py,soundcard.py,stream.py,rtlsdr.py}
    pipeline/{channel.py,supervisor.py,watchdog.py}
    recording/{ringbuffer.py,recorder.py,encoder.py,retention.py}
    alerts/{base.py,dispatcher.py,mqtt.py,ha_discovery.py,webhook.py,script.py}
    api/{app.py,auth.py,ws.py,routes/}
    storage/{db.py,models.py,migrations/}
    integrations/{zeroconf.py,supervisor.py}   # add-on options + discovery
    importers/tones_cfg.py                      # legacy tones.cfg import
  backend/tests/{unit,integration,golden,benchmarks,fixtures}
  web/{package.json,vite.config.ts,eslint.config.js,tsconfig.json}
  web/src/{api/generated,features/{dashboard,calls,tonesets,sources,alerts,spectrum,settings},components,lib}
  web/{tests,e2e}
  docker/{Dockerfile,compose.soundcard.yml,compose.stream.yml,compose.rtlsdr.yml}
  packaging/windows/tonewatch.spec
```

---

## Linting and quality standards (enforced in pre-commit **and** CI)

### Python (`backend/pyproject.toml`)
- **ruff** handles both linting and formatting, with `line-length = 100` and `target-version = "py313"`.
  - Enabled rules: `E W F I N UP B A C4 DTZ T20 SIM PTH RUF S ASYNC PL PERF FURB TRY RET ARG ERA TC D`, with the Google docstring convention on public API only.
  - Per-file ignores: `S101`, `PLR2004` and `D` for `tests/**`.
- **mypy `--strict`** with the pydantic plugin. `disallow_any_explicit` applies to `dsp/` and `config/`. numpy arrays are typed as `npt.NDArray[np.float32]`.
- **pytest** runs with `--strict-markers -W error`. Coverage gates: **≥85% overall, ≥95% for `dsp/` and `pipeline/`**.
- **Bans:** `print` (use `structlog`), bare `except`, `subprocess(shell=True)`, naive datetimes.

### Web
- TypeScript `strict`, plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` and `noImplicitOverride`.
- ESLint flat config: `typescript-eslint` `strictTypeChecked` + `stylisticTypeChecked`, `eslint-plugin-react`, `react-hooks`, `jsx-a11y` and `eslint-plugin-import-x`.
- **Prettier** handles formatting; ESLint does not do formatting.
- Vitest coverage must be ≥80%. Playwright smoke e2e runs against the compose stack with a file source.
- The generated API client is committed. CI fails if `pnpm gen:api` produces a diff.

### Repo-wide hooks (pre-commit)
ruff, mypy, prettier and eslint (as local hooks), plus:
- `hadolint` (Dockerfile)
- `shellcheck`
- `actionlint`
- `yamllint`
- `markdownlint-cli2`
- `gitleaks`
- `check-toml`, `check-json`, `end-of-file-fixer`, `trailing-whitespace`
- `codespell`

### justfile recipes (agents only ever call these)
- `setup`: `uv sync`, `pnpm install` and `pre-commit install`.
- `lint`, `fmt`, `typecheck`, `test`, `test-web`, `e2e`, `bench`, `gen-api`.
- `check`: runs `lint`, `typecheck`, `test`, `test-web`. **This must pass before every commit.**
- `dev`: runs the backend and Vite together.
- `docker-build`, `compose-up SOURCE=stream`.

---

## Security assurance: OWASP SAMM + DSOMM (added 2026-09-10)

The app is audited against two OWASP maturity models, and security work is scheduled as the **S track** alongside the milestones.

- **OWASP SAMM v2** (Software Assurance Maturity Model) covers 5 business functions and 15 practices: Governance, Design, Implementation, Verification and Operations. It measures *how the project builds software securely*.
- **OWASP DSOMM** (DevSecOps Maturity Model) covers the Build & Deployment, Culture & Organization, Implementation, Information Gathering and Test & Verification dimensions. It measures *how much security is automated in the pipeline*.
- **OWASP ASVS 5.0 Level 2** is the line-by-line **code standard**. SAMM and DSOMM are process maturity models and don't define code requirements, so ASVS supplies them. It is SAMM's Verification → Requirements-driven Testing practice made concrete.

### Target maturity (realistic for a small open-source, self-hosted app)
| Model | Target for v1.0 | Stretch |
|---|---|---|
| SAMM | **Level 1 in all 15 practices**, and **Level 2** in Threat Assessment, Security Requirements, Secure Build, Secure Deployment, Defect Management and Security Testing | Level 2 everywhere |
| DSOMM | **Level 1 in all dimensions**, and **Level 2** in Build & Deployment, Implementation and Test & Verification | Level 3 in Test & Verification |
| ASVS 5.0 | **Level 2** for the API, auth, WebSocket, file handling, webhook and script hook | n/a |

Practices that don't fit a solo project (for example, a formal security training programme or an incident response team) are marked **N/A with a written justification** rather than silently scored 0.

### Evidence layout (in the repo, reviewed like code)
```
docs/security/
  samm/assessment.yaml        # practice -> stream -> level, answer, evidence links, date
  samm/scorecard.md           # generated; baseline vs current vs target
  dsomm/activities.yaml       # DSOMM activity ids -> implemented | planned | n/a + evidence
  dsomm/scorecard.md
  asvs/checklist.csv          # ASVS 5.0 L2 requirement id -> status, code/test reference
  threat-model/tonewatch.json # OWASP Threat Dragon model (STRIDE)
  threat-model/README.md
  gaps.md                     # every gap -> GitHub issue label `security` + owner milestone
```
`scripts/security_scorecard.py` regenerates both scorecards from the YAML and fails CI if a claimed level has no evidence link.

### Pipeline controls this adds (the DSOMM Level 2 core)
These are wired into CI and pre-commit. Items marked ✓ already exist in the plan; ➕ items are new.

| Control | Tool | Where |
|---|---|---|
| SAST | CodeQL ✓, ruff `S` rules ✓, ➕ **Semgrep** (`p/python`, `p/typescript`, `p/owasp-top-ten`) | ci.yml |
| SCA / vulnerable deps | ➕ **pip-audit** (uv export), ➕ **osv-scanner** (both lockfiles), Renovate ✓ | ci.yml, and weekly on a schedule |
| Secrets | gitleaks ✓, GitHub push protection ✓ | pre-commit/CI |
| Container image | Trivy ✓, ➕ Trivy **config** scan (Dockerfile/compose misconfig), hadolint ✓ | docker.yml |
| Supply chain | SBOM ✓, cosign ✓, provenance ✓, SHA-pinned actions ✓, ➕ **OpenSSF Scorecard** action, ➕ `zizmor` (GitHub Actions security lint) | scorecard.yml, ci.yml |
| DAST | ➕ **OWASP ZAP baseline + API scan** (against `openapi.json`) run on the compose e2e stack | e2e job |
| License compliance | ➕ `pip-licenses` + `license-checker`, with a deny list for strong-copyleft licences (GPL/AGPL) in the MIT-licensed distribution; LGPL allowed only when dynamically linked (e.g. FFmpeg in PyAV wheels, which must be noted in THIRD_PARTY_NOTICES) | ci.yml |
| Runtime hardening | ➕ Container: non-root ✓, **read-only root fs**, `cap_drop: ALL`, `no-new-privileges`, tmpfs for /tmp | compose files, add-on config |

### Security review triggers
Milestones that change the attack surface (M5, M7, M8, M10, M11) each get a **targeted ASVS review sub-brief** after they pass functional review. Under the model policy it may run on a higher model (terra·high), scoped to the listed modules.

## GitHub setup (M0)

- **Visibility:** private until v1.0, then public. MIT license. Default branch `main`.
- **Branch ruleset on `main`:**
  - Changes go through a PR.
  - The required checks must pass.
  - History stays linear and merges are squash-only.
  - Force-push and deletion are blocked.
  - The conversation must be resolved before merging.
- **PR titles:** Conventional Commits, enforced by `amannn/action-semantic-pull-request`. `release-please` generates versions and CHANGELOG.
- **Dependencies:** Renovate groups updates weekly and automerges patch updates for dev dependencies only.
- **Security:**
  - Dependabot alerts, secret scanning and push protection are all on.
  - CodeQL runs for Python and JS.
  - `SECURITY.md` defines private vulnerability reporting.
- **Actions hardening:**
  - Actions are pinned by SHA, which Renovate keeps updated.
  - Each workflow sets least-privilege `permissions:`.
  - Nothing is pushed on PRs from forks.
- **Supply chain:** GHCR images are signed with **cosign** (keyless OIDC). They carry an SBOM (syft), an `actions/attest-build-provenance` attestation, and a Trivy scan that fails on HIGH/CRITICAL with a fix available.
- **Collaboration files:**
  - Labels: `milestone:Mx`, `area:dsp|sources|api|web|alerts|docker|ha|windows`, `blocked-on-user`, `good first issue`.
  - Issue forms: bug report, feature request and tone-detection-miss. The miss form asks for a WAV sample and the tone-set config.
  - `CODEOWNERS` is set to `@JustBeanie`.
- **Planning:** one GitHub Issue per task ID below, grouped under GitHub Milestones M0–M12.

### CI workflows
| Workflow | Jobs |
|---|---|
| `ci.yml` (PR + main) | lint-python · typecheck · test-python (matrix: ubuntu, windows, ubuntu-arm) · lint-web · test-web · api-client-drift · e2e (compose, file source) |
| `docker.yml` | buildx amd64/arm64 on PR (no push); on release, push to GHCR with cosign, SBOM, provenance and Trivy |
| `windows.yml` | PyInstaller onedir on windows-latest, smoke-run `tonewatch --version` + file-source detection test, upload artifact |
| `release.yml` | release-please; attach the Windows zip and checksums |
| `codeql.yml`, `pr-title.yml` | as named |

---

## Detection design (the core; must be exact)

- **Input normalization:** every source yields mono float32 at **16 kHz**. PyAV's resampler handles streams; sound cards are opened at their native rate and resampled.
- **Spectrum:** 4096-sample Hann window (256 ms), hop 1600 samples (100 ms). Peak search runs from 250 to 3000 Hz, with parabolic interpolation for sub-bin frequency.
  - **Tone purity** = peak-band energy ÷ total 250–3000 Hz energy.
  - A frame is "tonal" only if purity ≥ `purity_min` (default 0.6) and level ≥ `level_min_dbfs` (default −45). This rejects voice and noise.
- **Segmenter:** consecutive tonal frames whose frequency stays within ±`tol` of the running median form a segment `{freq, start, end, duration, mean_purity}`. It tolerates up to `max_dropout_frames` (default 2) of fade.
- **Tone set model:** `name, sequence: [ {freq_hz, tol_pct (default 1.5), min_s, max_s} ], max_gap_s (default 0.5), cooldown_s (default 60), enabled, alert_targets, record: {pre_roll_s, post_s, silence_stop_s, max_s}`.
  - Two-tone is a sequence of 2 tones. Long tone is a sequence of 1. N-tone sequences are supported for free.
- **Matcher:** runs an incremental state machine per tone set over the segment stream.
  - Emit **`ToneDetected` (pre-alert)** as soon as the final tone reaches `min_s`. Do not wait for the tone to end.
  - Latency target: under 300 ms after `min_s` is reached.
- **Stacked pages:** when another tone set matches during the post-roll window, merge it into the same call. The recording extends and is **trimmed of all tonal segments**, and each matched tone set is listed on the call.
- **Recording:**
  - The ring buffer holds pre-roll.
  - Post-roll runs until `post_s`, or stops early after `silence_stop_s` below the silence threshold.
  - The hard cap is `max_s`.
  - Encoding uses PyAV to MP3 (for compatibility and HA notifications) and optionally Opus.
  - Then **`RecordingReady`** is emitted.
- **Frequency counter:** the live dominant frequency, purity and spectrum stream over WebSocket at 5 Hz. The UI has a "capture this tone" button that pre-fills a tone set.

### Test strategy
- `dsp/generator.py` synthesizes test signals with parameters for:
  - frequency offset, amplitude, and white/pink noise at a chosen SNR
  - phase discontinuities, clipping and AM "voice-like" interference
  - timing jitter, stacked pages, and voice after the tones
- **Golden tests:** generated scenarios with exact expected calls.
- **Hypothesis property tests:**
  - Any tone set within tolerance and duration at SNR ≥ 10 dB is detected.
  - A tone off by more than 2×tol is never detected.
  - Pure noise or voice-like input produces 0 detections over 1 h of audio.
- **Benchmark:** 200 tone sets across 2 channels must process at least 20× realtime on CI x86. **Record baseline numbers for a Pi 4/5**; the user runs that manually.
- **Real-world fixtures:** the user supplies WAVs of their department's actual pages in `backend/tests/fixtures/private/`. That folder is gitignored, and those tests are skipped when it is absent.

---

## Milestones: agent-executable task list

Each task has an ID. Agents mark `[x]` in `docs/PROGRESS.md` and reference the ID in the PR title, e.g. `feat(dsp): M2.3 segmenter`.

### M0: Bootstrap
- **M0.1** Create the local repo layout, `LICENSE`, `README` skeleton, `.editorconfig`, `.gitattributes` (LF everywhere, `*.wav binary`) and `.gitignore`.
- **M0.2** Create `backend/pyproject.toml` (uv, ruff, mypy, pytest config as above). Add `src/tonewatch/__main__.py` with `--version`.
- **M0.3** Create `web/` with Vite React-TS, the strict tsconfig, ESLint flat config, Prettier and Vitest. Add one passing test.
- **M0.4** Add the `justfile` and `.pre-commit-config.yaml` with all hooks.
- **M0.5** Add `ci.yml`, `pr-title.yml`, `codeql.yml`, `renovate.json`, issue/PR templates, `CODEOWNERS`, `SECURITY.md` and `CONTRIBUTING.md`.
- **M0.6** **Spike (blocking):** verify on ubuntu, windows and ubuntu-arm CI that PyAV wheels can **encode MP3 (libmp3lame) and Opus**, and that `sounddevice` imports.
  - Write the findings to `docs/decisions/0001-audio-libs.md`.
  - Fallback: `lameenc`.
- **M0.7** 🛑 **USER GATE:** create the GitHub repo, apply the ruleset, enable security features and push. Agents prepare a `scripts/gh-bootstrap.sh` using `gh` but **do not run it**.
- **Done when:** `just setup && just check` is green locally and CI is green on the first PR.

### M1: Domain, config and storage
- **M1.1** Pydantic models: `ToneSet`, `ToneSpec`, `Source` (discriminated union: soundcard, stream, rtlsdr, file), `AlertTarget` (mqtt, webhook, script) and `RecordingPolicy`. All validation is covered by unit tests.
- **M1.2** `config/store.py`: load and save YAML at `$TONEWATCH_DATA/config.yaml`.
  - Writes are atomic (temp file + rename).
  - Env overrides come through pydantic-settings.
  - In add-on mode, config is read from `/data/options.json`.
- **M1.3** SQLAlchemy async models `Call`, `CallToneSet`, `Recording`, `AlertAttempt`, the Alembic initial migration, and repository functions.
- **M1.4** `events.py`: typed domain events and an asyncio `EventBus` with multiple subscribers. A slow subscriber must not block the others.
- **Done when:** tests pass, coverage gates are met, and mypy strict is clean.

### M2: DSP engine (highest-risk area; do it thoroughly)
- **M2.1** `generator.py` with every synthesis feature listed above, plus a `tonewatch-gen` CLI that writes a WAV.
- **M2.2** `spectrum.py`: framing, window, FFT, parabolic interpolation, purity and level. Test frequency accuracy to ±0.5 Hz on pure tones from 300 to 3000 Hz.
- **M2.3** `segmenter.py`, with dropout tolerance and median tracking.
- **M2.4** `matcher.py`: the per-tone-set state machine, `max_gap`, cooldown and early pre-alert.
- **M2.5** Golden scenario suite of at least 25 scenarios: clean, noisy, off-frequency, too short, too long, stacked, back-to-back same set within cooldown, voice-only, clipping.
- **M2.6** Hypothesis property tests and the benchmark (`just bench`), with the results recorded in `docs/benchmarks.md`.
- **M2.7** `tonewatch analyze file.wav --config config.yaml` prints the detected calls and segments. This is the main debugging tool for missed pages.
- **Done when:** every golden and property test passes, false positives are 0 on 1 h of synthetic voice/noise, and the benchmark is ≥20× realtime.

### M3: Sources and pipeline
- **M3.1** `sources/base.py`: an `AudioSource` async iterator protocol, frame dataclass, and lifecycle (`open`/`close`).
- **M3.2** `file.py` in realtime and fast modes. It is used by all integration tests and e2e.
- **M3.3** `soundcard.py` (sounddevice callback → asyncio queue, device selection by name/index, channel select L/R/mix). Also add `tonewatch devices` to list inputs.
- **M3.4** `stream.py`: PyAV decode of HTTP/Icecast/RTSP with exponential backoff reconnect. Test it against a local stream served by an ffmpeg fixture in integration tests.
- **M3.5** `rtlsdr.py`: an `rtl_fm` subprocess with frequency, gain, ppm and squelch, reading s16le from stdout, restarting on exit, and **no shell**. Test it with a fake `rtl_fm` script.
- **M3.6** `pipeline/channel.py` (source → ringbuffer → DSP → recorder) and `supervisor.py`, which runs N channels and restarts crashed ones with backoff.
- **M3.7** `watchdog.py`: no frames for more than 10 s, flatline (RMS < −80 dBFS) for more than N min, clipping ratio, and stream disconnect. Emits `FeedHealthChanged`.
- **Done when:** an integration test runs 2 file channels concurrently through the supervisor and the expected calls land in the DB.

### M4: Recording
- **M4.1** Ring buffer pre-roll, then post-roll with silence early-stop and the max cap.
- **M4.2** Tonal-segment trimming and stacked-page merge.
- **M4.3** `encoder.py`: MP3 plus optional Opus, with metadata tags (tone set names, timestamp). Files go to `recordings/YYYY/MM/DD/<call_id>.mp3`, or `/media/tonewatch/...` in add-on mode.
- **M4.4** `retention.py`: max age, max total size and max count, run by a daily job.
- **Done when:** golden stacked-page scenarios produce one trimmed recording containing the expected voice duration ±0.3 s.

### M5: API
- **M5.1** FastAPI app factory, lifespan starting the supervisor, structlog JSON logs, and `/healthz` plus `/readyz`.
- **M5.2** Auth: a bearer API token generated on first run and stored in the data dir, with an optional UI password.
  - **Trusted HA ingress:** requests from `172.30.32.2` with `X-Ingress-Path` skip the password. Every URL the app builds must respect the ingress base path.
- **M5.3** REST: CRUD for tone sets, sources and alert targets (persisted to YAML and hot-applied); calls list and detail; recording download with Range support; `POST /api/tonesets/{id}/test` to simulate a detection; `GET /api/devices`; and `POST /api/analyze` (WAV upload runs M2.7 and returns segments).
- **M5.4** WebSocket `/api/ws`: domain events, per-channel levels, and spectrum at 5 Hz when a client subscribes.
- **M5.5** `zeroconf.py` advertises `_tonewatch._tcp`. `supervisor.py` posts Supervisor discovery (`/discovery`, service `tonewatch`) in add-on mode.
- **M5.6** `openapi.json` is exported to `web/src/api/generated` via `just gen-api`, with a CI drift check.
- **Done when:** API integration tests use httpx AsyncClient and a WS test client, covering auth-rejection paths.

### M6: Web UI
- **M6.1** App shell, auth, ingress-aware base path (`base: './'`) and a light/dark theme.
- **M6.2** **Dashboard:** live call feed, channel levels and feed health.
- **M6.3** **Calls:** a list with filters and a detail view with an audio player, matched tone sets and alert attempt results.
- **M6.4** **Tone sets:** a CRUD form with validation, a "test" button, and import from legacy `tones.cfg` files (M8.x importer).
- **M6.5** **Frequency counter / spectrum:** a canvas spectrum, dominant frequency readout and "capture tone".
- **M6.6** **Sources:** device picker, stream URL, and RTL-SDR parameters, with live level preview.
- **M6.7** **Alerts** configuration with a "send test" button, and **Settings** for retention, auth and MQTT.
- **M6.8** **Analyze:** upload a WAV and view the segment timeline. This is the debugging page.
- **M6.9** Playwright e2e: create a tone set, the compose stack with a file source plays the fixture, the call appears in under 10 s, and the audio plays.
- **Done when:** eslint and tsc are clean, Vitest coverage is ≥80%, e2e is green, and the jsx-a11y rules pass.

### M7: Alerts
- **M7.1** `dispatcher.py` subscribes to events and maps tone sets to targets. It adds per-target retry with exponential backoff (max 5), dedupe by call ID, and writes an `AlertAttempt` row for each attempt.
- **M7.2** `mqtt.py` (aiomqtt): LWT availability topic, `tonewatch/<instance>/call` and `.../health/<channel>` topics, and retained config.
- **M7.3** `ha_discovery.py`: a device per instance, an `event` entity per tone set (event_types `pre_alert`, `recording_ready`; attributes carry `recording_url`), `sensor.last_call`, `binary_sensor.call_active`, and `binary_sensor.<channel>_feed_healthy`. Deleting a tone set clears its retained discovery.
- **M7.4** `webhook.py`: JSON POST with an HMAC-SHA256 signature header, timeout, and an optional multipart audio attachment.
- **M7.5** `script.py`: **off by default**. It uses an allowlisted executable path and an argv list with `{call_id}`/`{recording_path}`/`{toneset}` substitution, with no shell, a timeout, and output captured to the attempt log.
- **Done when:** an integration test uses an embedded MQTT broker (amqtt fixture or mosquitto testcontainer) to assert the discovery and event payloads, and webhook tests assert the signature.

### M8: Docker, release and importer
- **M8.1** Multi-stage `Dockerfile`:
  - Node stage builds the web UI.
  - `python:3.13-slim` + uv stage builds a venv.
  - The runtime stage has `libportaudio2`, `rtl-sdr`, `tini`, the non-root `tonewatch` user in the `audio` and `plugdev` groups, `/data` as a volume, and a `HEALTHCHECK`.
- **M8.2** Compose examples for soundcard (`devices: /dev/snd`, `group_add: audio`), stream, and rtlsdr (`/dev/bus/usb`, plus a note on blacklisting `dvb_usb_rtl28xxu` on the host).
- **M8.3** `docker.yml` with buildx multi-arch, cosign, SBOM, provenance and Trivy. On `release.yml`, release-please tags and GHCR pushes `:X.Y.Z`, `:X.Y` and `:latest`.
- **M8.4** `importers/tones_cfg.py`: 🛑 **BLOCKED-ON-USER.** The user must supply a sample legacy `tones.cfg` file so the format can be confirmed. Agents build the importer interface and tests against that sample only once it exists.
- **Done when:** the image builds for both archs, the container runs the e2e stack, Trivy is clean, and the image is under 350 MB.

### M9: Windows native
- **M9.1** PyInstaller onedir spec bundling the built web UI, PortAudio (shipped in the sounddevice wheel) and PyAV. Data dir is `%PROGRAMDATA%\tonewatch`.
- **M9.2** `tonewatch service install|uninstall` via NSSM docs *or* a pywin32 service wrapper, documented in an ADR.
- **M9.3** `windows.yml` builds, smoke-tests (`--version`, `devices`, `analyze` on a fixture WAV) and uploads the zip. Code signing is backlog.
- **Done when:** the CI artifact runs the analyze smoke test on windows-latest.

### M10: HA add-on (in `JustBeanie/ha-addons`)
- **M10.1** `tonewatch/config.yaml` settings:
  - `image: ghcr.io/justbeanie/tonewatch`, `arch: [aarch64, amd64]`
  - `ingress: true`, `ingress_port: 8080`, `panel_icon: mdi:fire-truck`
  - `audio: true` (sound card through HA's PulseAudio), `usb: true` (RTL-SDR)
  - `map: [media:rw]`, `services: [mqtt:want]`, `discovery: [tonewatch]`
  - `init: false` (the image uses tini)
  - `options`/`schema` for bootstrap settings; tone sets are managed in the UI
- **M10.2** The app, in add-on mode, fetches MQTT credentials from the Supervisor `/services/mqtt` endpoint, writes recordings to `/media/tonewatch`, and posts discovery.
  - **Verify** which of `hassio_api` or `services` permissions the credentials fetch needs, and document the result.
- **M10.3** Add `DOCS.md`, `CHANGELOG.md`, icon/logo and `translations/en.yaml`. Run `frenck/action-addon-linter` in that repo's CI.
- **Done when:** the add-on linter passes. 🛑 **USER GATE:** install on the real HA box, then run the hardware-in-the-loop checklist below.

### M11: HA custom integration (`JustBeanie/ha-tonewatch`)
- **M11.1** Scaffold `custom_components/tonewatch/` (manifest with `zeroconf: ["_tonewatch._tcp.local."]`, `config_flow`, `iot_class: local_push`), plus `hacs.json`, ruff, mypy and `pytest-homeassistant-custom-component`.
- **M11.2** Config flow supporting user entry (host, port, token), `async_step_zeroconf`, `async_step_hassio` (Supervisor discovery) and reauth.
- **M11.3** `api.py` WebSocket client using HA's aiohttp session, with reconnect/backoff and a `DataUpdateCoordinator` fed by push.
- **M11.4** Entities:
  - `event` per tone set
  - `sensor` last call
  - `binary_sensor` call active and feed health per channel
  - `switch` tone set enabled
  - `button` test tone set
  - A `tonewatch_detected` bus event carrying `recording_url` and `media_content_id`
- **M11.5** `media_source.py` browses calls by date and resolves to authenticated recording URLs proxied through HA, so the token never reaches the client.
- **M11.6** `diagnostics.py` (token redacted), `strings.json`/translations, and repairs for app/integration version mismatch.
- **M11.7** Blueprints:
  - (a) Play the dispatch recording on a chosen `media_player` when a tone set fires.
  - (b) Send a mobile notification with the recording attached or linked. iOS supports audio attachments; **verify Android behavior and document it**.
- **M11.8** CI: hassfest, `hacs/action`, ruff, mypy and pytest. Aim for HA **integration quality scale Silver** rules.
- **Done when:** all CI is green and the tests cover config flow (all steps), entity creation from a mocked WS stream, and media_source browse/resolve.

### M13: Tone auto-discovery (added 2026-09-12 at user request; ships before v1.0)
Finds tone pages that no configured tone set matches, so users can see what is being paged on their feed and turn it into a tone set in one click. It builds on the M6.5 "capture tone" pre-fill.
- **M13.1** `dsp/discovery.py`, per channel, fed by the existing segmenter output:
  - **Candidates:** group stable tonal segments separated by at most `max_gap_s` into sequences:
    - two-tone: two segments, each 0.3–3 s
    - long tone: one segment of at least 2 s
    - sequences of up to 5 tones
  - **Reported only when unmatched:** a candidate counts as "discovered" only when **no enabled tone set** matched it (it consults the matcher's result for that time span), and it passes the purity and level gates.
  - **Rejected:** DTMF-like simultaneous pairs, and anything outside 250–3000 Hz.
  - **Output:** a `ToneDiscovered` domain event.
- **M13.2** **Clustering and storage.**
  - **Clustering:** observations whose tones agree within `tol_pct` (default 1.5 %) merge into one cluster with running mean frequencies, median durations, count, first/last seen and source ids.
  - **Storage:** a `DiscoveredTone` table + Alembic migration, with caps (at most 1,000 clusters, oldest-unseen pruned by the retention job).
  - **User marks:** a cluster can be marked *dismissed*, so it's never re-suggested, or *promoted*.
- **M13.3** **Evidence clip (optional, default on).**
  - **Clip:** each new cluster keeps its best observation as a short encoded clip: the tones plus up to 15 s after, via the existing encoder.
  - **Retention and privacy:** clips count toward recording retention and are deleted with their cluster. The same privacy notes apply as for recordings.
- **M13.4** **API + WS.**
  - `GET /api/discovered-tones` (filters: source, since, status).
  - `POST /api/discovered-tones/{id}/promote` returns a pre-filled `ToneSet` draft: frequencies, tolerance derived from the cluster's observed spread (clamped), durations and name "Discovered 612.4/2222.2 Hz".
  - `POST .../dismiss` and `DELETE`.
  - Clip download with Range.
  - WS `tone_discovered` event.
  - Everything requires auth + CSRF like other routes.
- **M13.5** **UI "Discovered tones" page.**
  - Table of frequencies, durations, times heard, last heard, source, clip player, **Create tone set** (opens the tone-set form pre-filled), and **Dismiss**.
  - Dashboard badge for new discoveries.
- **M13.6** **Notifications (off by default, to avoid noise).**
  - An optional HA/MQTT `event` entity `tone_discovered` and a webhook event type.
  - The M11 integration exposes a `sensor` "last discovered tone".
- **M13.7** **Settings.**
  - `discovery.enabled` (default true), minimum durations, clip on/off, and per-source opt-out.
  - `tonewatch analyze` gains `--discover`, which lists unmatched candidates for a WAV file.
- **Done when:**
  - **Golden scenarios pass:**
    - an unknown two-tone gives exactly one cluster
    - a known tone set gives no discovery
    - repeats with ±0.5 % jitter give one cluster with count 2+
    - tones more than 2×tol apart give separate clusters
    - a stacked known + unknown page gives one call plus one discovery
  - **Zero discoveries** over the 1-hour synthetic voice/noise corpus.
  - **Hypothesis property:** clustering is order-independent.
  - **Promote → save → replay** of the same audio produces a detection.

**Order for M14–M16 (added 2026-09-12 at user request; they ship before v1.0):**
1. Backends first, in parallel: M14.1–M14.3 ∥ M15.1–M15.4 ∥ M16.1–M16.3.
2. Then the UIs: M14.4, M15.5, M16.4.
3. Then the Home Assistant parts (M14.5, M16.5), after M11.4/M11.5.

### M14: Live audio restream
Lets users listen to a source live, in the web UI and on any Home Assistant `media_player`. Rebroadcasting radio traffic may be regulated where the user lives, so the feature is **off by default** and never reachable without auth.
- **M14.1** `streaming/live.py` `LiveHub`, a per-source fan-out tapped from `Channel` after normalization (16 kHz mono float32):
  - **Encoder:** starts only while at least one listener is connected (no listeners, no CPU). It uses PyAV incremental MP3 (CBR, mono, 44.1 kHz, `bitrate_kbps` default 48). Packets are self-framed, so concatenated packets form a valid stream.
  - **Listener isolation:** each listener has a bounded queue of about 2 s. A slow listener drops its oldest chunks and is disconnected once it falls too far behind. **The pipeline never awaits a listener.**
  - **Squelch gate:** while squelch (M15) is closed, the stream carries encoded silence so players keep the connection. Until M15 lands the gate is always open.
- **M14.2** **API.**
  - `POST /api/sources/{id}/live-url` (auth + CSRF) returns `{url, expires_at}` for `GET /api/sources/{id}/live.mp3?t=<token>`.
  - **Token:** HMAC-SHA256 over source id, expiry, nonce and scope `live`, keyed by a separate secret in the data dir (created on first use, owner-only permissions).
    - Scoped to one source and compared in constant time.
    - TTL defaults to 3600 s, maximum 86400 s.
    - Never logged: the query string is redacted from access logs.
  - **Live endpoint:** accepts the normal API auth or a valid signed token. The response is chunked `audio/mpeg` with `Cache-Control: no-store` and no Range support.
  - **Caps:** `max_listeners_per_source` (default 4) and `max_listeners_total` (default 12); over the cap returns 503. Listener counts appear in WS and in the source status.
  - **URLs:** built ingress-aware; `public_base_url` is used for URLs handed to external players.
- **M14.3** **Settings and audit.**
  - `live_stream.enabled` (default **false**), `bitrate_kbps`, the caps and `token_ttl_s`.
  - Per-source `live_stream_enabled` (default true when the global switch is on).
  - An audit event for each URL issued.
- **M14.4** **Web UI.**
  - "Listen live" on dashboard and source cards (HTML audio), plus the listener count.
  - "Copy player URL" showing its expiry.
  - The rebroadcast disclaimer beside the settings toggle.
- **M14.5** **Home Assistant.** MQTT can't carry live URLs because they expire. In `ha-tonewatch`, after M11.5:
  - A `media_source` "Live" folder per source that mints a fresh signed URL at resolve time.
  - A `tonewatch.play_live` service (source, `media_player`, duration).
  - A blueprint: "play the live feed on a speaker when a tone set fires, stop after N minutes".
- **M14.6** **Threat model, ASVS rows and docs.** Cover signed-URL leakage through player logs, listener-exhaustion DoS, and scope. Add a docs page "Listen live" with the disclaimer.
- **Done when:**
  - 2+ concurrent listeners decode valid MP3 from a file source.
  - A stalled listener does not delay detection (bounded latency asserted).
  - Expired, tampered and wrong-source tokens are rejected; caps return 503.
  - No encoder runs with zero listeners.

### M15: Squelch
Software squelch for every source type, so activity is visible and live audio carries silence instead of noise. **Squelch never gates detection:** the detector always sees raw audio, because tones can start before squelch opens.
- **M15.1** `dsp/squelch.py`, a pure state machine:
  - `SquelchConfig {mode: off|level|noise_floor, open_dbfs: -40, close_dbfs: -45, attack_ms: 50, hang_ms: 1500, floor_margin_db: 10}`, with `close_dbfs ≤ open_dbfs` validated.
  - **Behaviour:** hysteresis between open and close, attack before opening, hang before closing.
  - **`noise_floor` mode:** tracks the floor with a slow low-percentile estimator (the quietest ~10 % of frames over a rolling window) and opens at floor + margin.
- **M15.2** **Config.**
  - `SourceBase.squelch: SquelchConfig` (default `mode: off`).
  - The existing RTL-SDR `rtl_fm -l` integer becomes `RtlSdrSource.rtl_fm_squelch`. A legacy integer `squelch` on an rtlsdr source is accepted and migrated on load and save.
  - The watchdog treats squelch-closed audio (including `rtl_fm` digital silence) as expected, not a flatline fault.
- **M15.3** **Pipeline.**
  - Per-channel squelch state and a `SquelchChanged(source_id, open, level_dbfs, at)` event.
  - The WS level payload gains `squelch_open`.
  - The M14 live stream follows the gate.
  - Optional `record.stop_on_squelch` (default false) ends post-roll on squelch close + hang instead of the silence threshold.
- **M15.4** **Outputs.** An MQTT/HA discovery `binary_sensor` "<source> activity" (squelch open) and `last_activity_at` in the source status. ha-tonewatch picks both up in M11.4.
- **M15.5** **Web UI.**
  - Squelch controls on the source form.
  - The live level meter shows the open and close lines and an open/closed lamp.
  - "Set from noise floor" fills open/close from the current floor + margin.
- **Done when:**
  - Unit tests cover hysteresis, attack and hang.
  - **Hypothesis property:** noise hovering between close and open never chatters (at most one transition per hang window).
  - **Golden:** voice bursts in noise give one open/close pair per burst.
  - A tone page arriving while squelch is closed is still detected with unchanged latency.
  - The legacy rtlsdr integer migrates.

### M16: Agencies and map
Rich per-agency data so every page says *who* was toned out, plus a map of agencies and their coverage.
- **M16.1** **`Agency` config model** in `AppConfig.agencies` (at most 500):
  - **Identity:** `id`, `name`, `short_name`, `kind` (`fire|ems|police|rescue|dispatch|other`), `color` (hex), `description`.
  - **Place:** `address` (street, city, region, postal code, country), `location {lat, lon}` (ranges validated), and `stations: [{name, address, lat, lon}]`.
  - **Coverage:** an optional GeoJSON Polygon/MultiPolygon, with closed rings, at most 10,000 vertices and 256 KB.
  - **Contact and notes:** `contacts` (phone; website http/https only), `radio` notes (channel/talkgroup), `tags`, `notes` (at most 4,000 chars).
  - **Link to tone sets:** `ToneSet.agency_id` (optional, reference-checked). Deleting an agency that tone sets still reference is rejected, and the error lists those tone sets.
- **M16.2** **API.**
  - CRUD `/api/agencies` (auth + CSRF + audit, like tone sets).
  - `GET /api/agencies.geojson`: a FeatureCollection of locations, stations and coverage.
  - Calls and call detail include the agency.
  - Migration `0005` stores an agency snapshot (`agency_id`, `agency_name`, `agency_kind`) on `CallToneSet`, so history survives renames and deletes.
  - Event payloads (WS, MQTT, webhook, HA `tonewatch_detected`) gain `agency {id, name, short_name, kind, lat, lon}`.
- **M16.3** **Map settings.**
  - `map.tile_url` defaults to empty, which means **no external requests**: markers and coverage draw on a plain background.
  - `map.attribution`, plus a one-click OpenStreetMap preset in the UI that carries the attribution OSM requires.
  - The SPA CSP adds only the configured tile origin to `img-src`.
- **M16.4** **Web UI.**
  - Agencies list and editor: click the map to set the location or stations; upload or paste GeoJSON coverage.
  - A **Map** page (Leaflet) with markers and coverage coloured by kind. Clicking one opens an agency card with its tone sets and recent calls.
  - Active calls pulse the agency marker live, and the calls list filters by agency.
- **M16.5** **Home Assistant.** MQTT events carry the agency. In ha-tonewatch, after M11.4, a `geo_location` entity per active call sits at the agency location so it shows on HA's map, and is removed when the call closes.
- **Done when:**
  - **Validation tests:** bad coordinates, open rings, oversize coverage, dangling references.
  - **API tests,** including the GeoJSON shape.
  - The call snapshot survives an agency rename and delete.
  - A CSP test proves there is no external origin without `map.tile_url`.
  - **Playwright:** create an agency, place it on the map, link a tone set; a file-source page shows the agency on the call and pulses it on the map.
- **Backlog:** opt-in address geocoding (external service), drawing coverage polygons in the UI, importing agency layers (for example county GeoJSON).

### M12: Docs, hardening and v1.0.0
- **M12.1** mkdocs-material site: install guides (Docker, Pi, add-on, Windows), finding tone frequencies, tuning purity/tolerance, troubleshooting missed pages with `analyze`, and HA recipes. Publish with GitHub Pages.
- **M12.2** Update the S3 threat model for anything added since. Confirm the webhook SSRF allowlist blocks link-local and metadata IPs by default.
- **M12.3** README disclaimer: this is a **supplemental notification tool, not a certified primary alerting system**, and recording or rebroadcasting radio traffic may be regulated locally.
- **M12.5** *(after M8.4, M10a, M13 land; before M12.4)* Clean-room naming scrub: no tracked reference to the legacy product name or its abbreviation. Rename the importer, route, CLI, audit event, fixtures and docs to neutral `tones.cfg` wording, and add a pre-commit pygrep gate. Brief: `docs/pm/briefs/M12.5-name-scrub.md`.
- **M12.4** Release-please cuts v1.0.0 and the integration v1.0.0 is tagged. The user installs through HACS and runs the checklist.

### S track: Security assurance (OWASP SAMM · DSOMM · ASVS)
- **S1** *(after M1)* **Baseline assessment.**
  - Create the `docs/security/` layout.
  - Score SAMM (all 15 practices, both streams) and DSOMM activities against the **current** repo, with honest scores and evidence links.
  - Write the target table above into the YAML.
  - Generate the scorecards and `gaps.md`.
  - Add `scripts/security_scorecard.py` with tests.
- **S2** *(after S1)* **DSOMM Level 1–2 pipeline controls.**
  - Add Semgrep, pip-audit, osv-scanner, zizmor, license checks, the Trivy config scan and the OpenSSF Scorecard workflow.
  - Add local `just security` running everything that can run offline or locally.
  - Run the tools and triage every finding: fix it, or document an accepted risk with an expiry date.
- **S3** *(after M5)* **Threat model** (SAMM Threat Assessment L2). STRIDE over the data-flow diagram: audio sources, API/WS, HA ingress, MQTT, webhooks, script hook, recordings on disk, add-on Supervisor token. Each threat maps to a mitigation task or an accepted risk. This **replaces M12.2**, which becomes "update the threat model".
- **S4** *(after M7)* **ASVS 5.0 L2 code audit.**
  - Covers authentication/session, access control (ingress trust), input validation (config, uploads, WAV parsing), output encoding (UI), file handling (path traversal in recording download), SSRF (webhook), command execution (script hook), logging (no secrets), and error handling.
  - Every requirement is marked pass, fail or N/A with a code or test reference.
  - Failures become fix tasks, and **every fix gets a regression test**.
- **S5** *(after M8)* **DAST and container hardening.** Run the ZAP baseline and API scans in the e2e job. Apply read-only root fs, `cap_drop` and `no-new-privileges` to compose and the add-on. Verify the container still runs with sound card and RTL-SDR device mappings; record that in the hardware checklist.
- **S6** *(after M11)* **HA surface review.** ASVS checks on the integration: token redaction in diagnostics, the media_source auth proxy, WebSocket reconnect handling, and add-on permissions kept to least privilege (`hassio_api`, `services`, `map`).
- **S7** *(before M12.4 release)* **Final SAMM + DSOMM re-assessment.**
  - Update the scorecards with evidence.
  - Every target level is met, or the gap has an accepted-risk entry signed off by the user.
  - Publish the scorecards in the docs site and link them from `SECURITY.md`.
  - 🛑 **USER GATE:** the user signs off on accepted risks.

---

## AGENTS.md (content the agents follow; commit it verbatim in M0.1)

1. **Resume protocol.** Read `PLAN.md` and `docs/PROGRESS.md`. Pick the **lowest-numbered unchecked task whose dependencies are done** and that is not marked 🛑 or `BLOCKED-ON-USER`.
2. **One task means one branch** (`m2.3-segmenter`) and **one PR** with a Conventional Commit title that includes the task ID. Keep PRs small, under about 600 changed lines excluding lockfiles and generated files.
3. **Test-first for `dsp/`, `pipeline/` and `alerts/`.** Write the failing test, then the code.
4. **Before committing, run `just check`.** It must be green. Never use `--no-verify`, never lower coverage gates, and never add `# type: ignore`, `# noqa` or `eslint-disable` without a same-line justification comment.
5. **Never:**
   - commit secrets or real radio recordings
   - run `gh-bootstrap.sh`, push to GHCR, create repos, or publish releases
   - edit `PLAN.md` decisions; propose changes in `docs/decisions/NNNN-*.md` instead
6. **Updating the log.** When a task is done, tick it in `PROGRESS.md` with the PR link and one line of notes. When blocked, add a `BLOCKED:` line with the exact question, then move to the next unblocked task.
7. **When uncertain about external behavior** (a PyAV encoder, Supervisor API, or HA entity schema), write a spike test or ADR proving it before building on it.
8. **Stop condition.** Stop when every non-gated task is checked, or when only 🛑/BLOCKED tasks remain. Then write a summary at the top of `PROGRESS.md`.

**Dependency order:** M0 → M1 → S1 → S2 → M2 → M3 → M4 → M5 → S3 → (M6 ∥ M7) → S4 → M8 → S5 → (M9 ∥ M10 ∥ M13) → M11 → S6 → M12 (S7 before M12.4). M2 can start right after M1.1. M13 (tone auto-discovery) needs M2–M8 and must land before M11 so the integration can expose its sensor.

---

## Additional recommendations (backlog beyond v1; file as issues labeled `enhancement`)

- **Transcription:** optional local `faster-whisper` transcript per call, included in HA events and notifications. This is high value for dispatch audio.
- **Channels:** DTMF, 5-tone (CCIR/ZVEI) and MDC1200 decoding using the same segmenter/matcher pattern.
- **Operations:** a dead-feed alerting escalation (feed silent for X min → notify), which many departments want, plus a Prometheus `/metrics` endpoint.
- **Scheduling:** per-tone-set quiet hours and a per-target routing matrix.
- **Output:** Apprise targets (Pushover, ntfy, Telegram, Discord, email) for non-HA users. One dependency covers them all.
- **Backup:** config export/import and an HA backup-friendly data layout (the add-on `/data` is already included).
- **Streaming:** re-broadcast the live feed to Icecast/HLS so members can listen in-app.
- **Packaging:** multi-instance/cluster awareness (two receivers, dedupe calls by time window), plus Windows code signing and an MSI installer.
- **Replay:** a simulation mode that replays a day of recorded audio against a new config to preview detections before applying it.
- **Community fixtures:** an opt-in submission flow for anonymized tone snippets (no voice) to grow the golden test corpus.

---

## Verification

- **Security (S track):** `just security` is green. The SAMM and DSOMM scorecards meet their targets or have signed-off accepted risks. The ASVS L2 checklist has no unexplained `fail`. The ZAP baseline shows no High alerts. The OpenSSF Scorecard result is recorded.
- **Per PR (automated):** `just check`, the CI matrix (ubuntu, windows, arm), e2e on compose with a file source, docker build and Trivy, and the API-client drift check.
- **DSP confidence:** the golden suite, the property tests, 0 false positives over 1 h of noise/voice, and `docs/benchmarks.md`. Then `tonewatch analyze` on the user's real page WAVs (private fixtures) must detect 100% with correct tone sets.
- **Hardware-in-the-loop checklist (user, manual; lives in `docs/hil-checklist.md`):**
  1. Pi and USB sound card in Docker: key a signal generator or scanner, confirm the pre-alert in under 1 s after `min_s` and the recording is trimmed.
  2. RTL-SDR in Docker, tuned to the dispatch frequency; confirm detection.
  3. Broadcastify/Icecast stream; confirm reconnect after pulling the network for 60 s.
  4. HA add-on: ingress UI loads, recordings appear under Media → tonewatch, MQTT entities appear (or the integration auto-discovers), and the blueprint plays audio on a speaker.
  5. Windows build: select a WASAPI device, live spectrum works, detection works.
  6. Feed-health: unplug the audio and confirm the `feed_healthy` binary sensor goes off.
