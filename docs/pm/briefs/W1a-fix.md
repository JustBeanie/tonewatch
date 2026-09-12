# PM review: W1a fails on one race, one filesystem-path leak, one untested claim, and a hot-reload bug it exposed

What's good, and should stay as it is:
- The real-lifespan tests: no `channel_factory` fakes.
- The typed `RecorderHook` with the `TypeError` shim removed.
- The watchdog, recorder and retention wiring, and the recorder reset per call.
- The golden test changed only to pass `finish()` through.
- The pre-fix failure lines.

Fix exactly the findings below. You are resuming in the main checkout.

## 1. `AlertDispatcher._recording_url` is a race, and its fallback leaks a server filesystem path
`_recording_url` polls the DB with `for _ in range(100): … await asyncio.sleep(0)` for the `Recording` row that `PersistenceSubscriber` commits. `sleep(0)` doesn't wait for aiosqlite's worker thread, so on a slow or loaded host the loop can finish first. `_payload` then sets `"recording_url": recording_url or state.get("recording_path")`, which sends an **absolute server filesystem path** to every webhook, MQTT and HA consumer. The `except AttributeError: return None` also hides real errors.

**Fix it deterministically, with no polling:**
- After `session.commit()` for a `RecordingReady`, `PersistenceSubscriber` publishes a new typed event, `RecordingStored(call_id, recording_id, format, source_id)`.
- The dispatcher's `recording_ready` phase fires on `RecordingStored`, not on `RecordingReady`.
- `recording_url` is always `/api/recordings/{recording_id}` or `None`. It is never a path.
- Remove the `AttributeError` swallow.
- `recording_path` must not appear in any external payload (webhook, MQTT or HA discovery attributes). The script target may keep `{recording_path}` for argv substitution, because it's a local allowlisted process. Say so in `docs/security/webhook-signatures.md` or the threat model, whichever documents payload fields.
- Keep the existing M7 dedupe and retry semantics.

**Tests:**
- `test_recording_ready_alert_waits_for_persisted_row_without_polling`: the persistence session factory is wrapped so each commit takes ≥300 ms. The webhook still receives `recording_ready` with a `/api/recordings/<int>` URL that the app serves with 200.
- `test_external_alert_payloads_never_contain_filesystem_paths`: capture webhook JSON, MQTT publishes (fake client is fine here) and HA discovery attributes for a full call, and assert that no value contains the recordings root or `os.sep`-joined path fragments.
- `test_dispatcher_does_not_swallow_session_errors`: a session factory raising `AttributeError` surfaces as a failed `AlertAttempt` or a logged error, not a silent `None` URL.

## 2. Tone-set edits never reach running channels (found while reviewing your wiring)
`Supervisor.reload` only restarts sources whose `Source` config changed. Each channel and its `CallRecorder` are built with `self.config.tone_sets` **at channel start**. A tone set created, edited, disabled or deleted through `/api/tonesets` updates `self.config` and the dispatcher, but running channels keep detecting the old list until a source change or crash restart. A newly created tone set never fires on a live feed.
- **Fix:** when `config.tone_sets` changes, restart every running channel. That's acceptable because channel restart is cheap and bounded, and it finalizes the open call first. Alternatively, hot-swap the engine and recorder tone sets between frames. Pick one, explain it in the report, and make sure an in-progress call is finalized, not dropped.
- **Test:** `test_toneset_created_via_api_detects_on_running_channel`. It goes through `create_app`:
  1. Start with a looping realtime file source (injected fast clock/sleep is fine) and **no** tone sets.
  2. `POST /api/tonesets` a matching tone set.
  3. Assert a `Call` and a `Recording` row appear.
  4. Also `PUT` a disabled flag and assert no further calls start after it's applied.

## 3. Shutdown during post-roll: claimed but untested
Your report says the recording is finalized "on EOF/errors/shutdown". No test covers cancellation. `Channel.run` awaits `_close_call()` (encoding) inside `except BaseException` after `CancelledError`, bounded by `Supervisor.shutdown_timeout_s`.
- **Test:** `test_app_shutdown_during_post_roll_finalizes_recording_within_timeout`:
  1. Use a realtime looping source with injected clock/sleep and `post_s` long enough that the call is still open.
  2. Exit the lifespan context while it is open.
  3. Assert that afterwards (using a fresh session on the same DB file) a `Recording` row exists and its file is on disk.
  4. Assert shutdown took less than `shutdown_timeout_s + 1` s.
- If finalizing on cancel can't be made reliable, don't fake it. Document the limitation in an ADR and change the report claim. The test then asserts the call is closed with status `interrupted`, not left open.

## 4. Test robustness and blocking I/O
- In `test_webhook_alert_fires_for_real_recorded_call`, replace the 20×10 ms polling with an `asyncio.Event` set by the receiver on `recording_ready`, awaited with `asyncio.wait_for(..., 10)`. Apply the same pattern anywhere a W1a test polls with fixed tiny budgets (`test_retention_runs_in_app_lifespan` uses 20×`sleep(0)`).
- `PersistenceSubscriber._persist_recording` calls `av.open()` and `path.stat()` synchronously inside the event loop. Move them to `asyncio.to_thread`. No new test is needed beyond existing coverage, but keep `pipeline` ≥95.

## Constraints
- Stay in `backend/` and `docs/`.
- No `pragma: no cover`, no `mark.skip`, no unjustified suppressions, and no lowered coverage gates.
- Each new test must fail on the current tree first. Quote one failure line per test in the report.

## Definition of done
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Then run `just check` **last** and paste its unfiltered tail.
- `grep -rn "recording_path" backend/src/tonewatch/alerts` shows only script-target argv usage and internal state, with each remaining hit explained in the report.
- The final message has a **finding → fix (file:function) → test** table for findings 1–4.
- Update `docs/PROGRESS.md` W1a lines to cite the new tests.
