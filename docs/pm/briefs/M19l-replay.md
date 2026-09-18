# Brief: M19l — M19.12 replay recent calls or WAVs against a draft config (backend + API), plus one coverage top-up

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19l` (branch `m19l`). **E2E port:** `TONEWATCH_E2E_PORT=8854`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` **M19.12** (~line 691) and the backlog "simulation mode".
- `api/analyze.py` (`analyze_wav`, `analyze_wav_with_timeout`) and `api/routes/analyze.py`, the upload size and decode limits.
- `dsp/engine.py` `DetectionEngine`, and how `ToneSet` tuning affects matching.
- `storage/models.py` (`Call`, `CallToneSet`, `Recording`) and `recording/retention.py` `safe_recording_path`.
- The encoder: recordings are MP3/Opus, so see how `_read_wav` or the PyAV decode path can read them. Recordings are **tone-trimmed** (M4.2), so they may no longer contain the tones. **Find out and document it**: if trimmed recordings can't re-detect, replaying calls must use whatever pre-trim audio exists, or the feature must say plainly that replaying calls tests **voice-only** recordings and is limited to uploaded WAVs. Decide from evidence, and put the reasoning in your report.

## Required
1. **Replay endpoint:** `POST /api/admin/replay` with body `{draft: <AppConfig or just tone_sets + tuning>, calls: {last_n: 1..50} | null, uploads: [upload ids] | null}`.
   - Validate the draft through the normal `AppConfig` validation, restoring masked secrets like config import does. The draft is **never saved**.
   - For each call recording (through `safe_recording_path`) and each uploaded WAV, run detection off-loop with a per-item timeout and a total time/CPU budget (cap the total audio seconds, and document the cap).
   - **Result per item:** `actual` (the tone sets recorded for that call, or `null` for uploads), `draft` (the tone sets the draft detects, with detection times), and a classification: `would_detect` (in both), `would_miss` (in actual but not draft) or `new_detection` (in draft but not actual). Add summary counts.
   - Uses `authenticated` (it changes nothing) or `write_auth` if you judge the CPU cost warrants CSRF; say which and why. Rate-limit to one replay at a time (429), and audit it.
2. **Uploads for replay:** `POST /api/admin/replay/uploads` takes a WAV using the same size and format limits as `/api/analyze`, and stores it under `data_dir/replay-uploads/` with a random id. Uploads expire after 1 h (cleaned by the existing retention loop or a small task). Never accept a path from the client.
3. **Coverage top-up (separate small item):** `api/routes/import_tones_cfg.py` sits at 90.48 % against a 90 % gate on main. Add **behavioural** tests for its uncovered branches (read the coverage report) to bring it at least 1 % above the gate. No production changes unless a test exposes a bug.

## Mandatory tests (write first; show each failing line)
- **A. Classification:** using `dsp/generator.py` WAVs, a draft that matches → `would_detect`; a draft with the tone set's frequency moved out of tolerance → `would_miss`; a draft adding a new tone set present in the audio → `new_detection`. Summary counts are correct.
- **B. Calls:** seeded calls with real encoded recordings (use the encoder, or the fixture path other tests use) replay through the draft. Include the trimmed-recording finding from "Read first" as a test that documents the behaviour.
- **C. Safety:**
  - a draft with an invalid tone set gives 422
  - masked secrets in the draft restore, and a restore failure gives 422
  - the draft is never persisted (the config file hash and history version count are unchanged)
  - a recording path outside the root is skipped and reported, never read
  - the upload endpoint rejects oversize and non-WAV input, and stored names are random
  - a concurrent replay gives 429
  - the total-audio cap is enforced
  - no auth gives 401
  - it's audited
- **D.** `import_tones_cfg.py` coverage at least 1 % above its gate, with the new test names listed.
- **E.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` fully green, with **every** `check_package_coverage.py` line at least 1 % above its gate. Paste the `dsp`, `api/routes/import_tones_cfg.py` and your new module lines. Then `just ci-local` up to `api-drift` (run `just gen-api`). `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result. Don't report `just check` as green unless you ran it in full after your last edit.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.12 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real audio or incident data.
- Put the replay routes in a new `api/routes/replay.py` (one router line in `api/app.py`). Add a threat-model row with id **TM-052** (M19i uses TM-050, M19j TM-051) with file:line evidence and a real test name. The threat-model test validates this, so run it.
- **Parallel engineers:** M19i is in backup code, the CLI and `api/routes/admin.py`/`backup.py`; M19k is in `web/**`. Don't touch those.
