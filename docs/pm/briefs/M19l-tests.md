# Brief: M19l-tests — write the mandatory replay tests A–E, fix what they expose, and reach the gates

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b696-5d71-7810-92d7-c126a44d0921`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19l` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8854`. `docs/pm/briefs/M19l-replay.md` still applies in full.

## Status
Your honest partial report: `api/routes/replay.py` exists, but only a few classification tests exist, and the full `just check` pytest phase never finished. The code exists now, so these tests must be **behavioural and adversarial**, aimed at finding bugs in what you wrote. For each test, record whether it passed immediately or failed; for each failure, show the fix with file:line. **Paste results into your progress messages as you go**, in case your turn is cut off.

**If the full pytest run doesn't finish in your sandbox, run it in chunks**: `backend/tests/unit`, `backend/tests/integration` and `backend/tests/golden`, each with `--basetemp` outside the repo. Paste each summary line, then run the coverage and package-gate step (`check_package_coverage.py`) on the combined result. Don't skip it.

## Required tests (the M19l brief A–E, in full)
- **A. Classification:** WAVs from `dsp/generator.py`.
  - A matching draft gives `would_detect`.
  - Moving the tone set's frequency out of tolerance gives `would_miss`.
  - A new tone set present in the audio gives `new_detection`.
  - A draft with **no** tone sets gives all `would_miss` for calls, and empty results for uploads.
  - Summary counts match.
- **B. Calls:**
  - Seeded calls with real encoded recordings (use the encoder or the existing fixture path) replay through the draft.
  - Your code says stored recordings are tone-trimmed voice clips. **Write a test that documents that**: a call recorded from a generated page, replayed against the same config, is **not** re-detected. Assert the per-item note explaining why. Make sure the response and `docs/guide/admin.md` say plainly that replaying calls is only meaningful for configs detecting tones in voice-bearing audio, and that uploads are the main path.
  - If you conclude that call replay is misleading as designed, say so in the report. The PM decides whether to keep it.
- **C. Safety:**
  - An invalid draft tone set gives 422.
  - Masked secrets in the draft restore, and a restore failure gives 422.
  - **The draft is never persisted**: the config file hash, the history version count and `app.state.config` are unchanged.
  - A recording path outside the root is skipped and reported, never opened (patch `open` or the decoder and assert it's never called with that path).
  - Uploads: oversize gives 413, non-WAV gives 422, stored names are random, and a client-supplied path or id with `..` is refused.
  - Uploads expire after 1 h (injected clock), and the replay of an expired id gives 404.
  - A concurrent replay gives 429.
  - The total-audio cap is enforced, with a readable message.
  - No auth gives 401. If you chose `write_auth`, a cookie without CSRF gives 403.
  - It's audited, with the draft never written into the audit row.
- **D. Coverage:** `api/routes/import_tones_cfg.py` coverage at least 1 % above its 90 % gate (it's 90.48 % on main), with the new behavioural test names listed.
- **E.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, marking "passed immediately" or showing its failing line, the fix (file:line) and its passing line.
- The complete pytest summary (full or chunked, as above), and **every** `check_package_coverage.py` line at least 1 % above its gate. Paste `dsp`, `api/routes/replay.py` and `api/routes/import_tones_cfg.py`.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always. Don't claim green without the pasted summary lines.

## Standing rules
- As in M19l. **Parallel engineer M19k** is in `web/**`. Main has moved: backup (M19i) landed and added `api/routes/backup.py` and `instance_lock.py`. Don't touch those. The PM rebases.
