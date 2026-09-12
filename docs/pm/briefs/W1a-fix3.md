# PM review: W1a-fix2 fails. Startup reconcile deletes user files, and shutdown leaks tasks.

What's good, and should stay as it is:
- the separate finalize and drain budgets
- shielded encode and commit
- ADR-0006 option (b)
- the three deterministic injected-delay tests (the old wall-clock test is gone)
- the `local_attachment_path` rename
- the bounded retention helper

Resume in the `tonewatch-hotfix` worktree. Fix exactly the two findings below.

## A. Data loss: startup reconcile deletes audio files the app didn't create
In `PersistenceSubscriber.reconcile_orphans`, any `.mp3`/`.ogg` under the recordings root whose stem isn't a UUID hits `except ValueError: … await asyncio.to_thread(path.unlink, True)`. Nothing asked for that, and nothing tests it.

**PM probe on your tree:** with a fresh DB, the recordings root held `user-note.mp3` and `2026/09/11/2026-09-11 dispatch.ogg`. After `reconcile_orphans(root)` **both files were gone**.

In the HA add-on the recordings root is `/media/tonewatch`, inside Home Assistant's shared media library. Users browse, copy and rename files there, so every restart would silently delete them.

**Fix:**
- Reconciliation **never deletes anything**.
- Files whose stem isn't a UUID are skipped and logged once at `info`, with the count and relative paths, no absolute paths.
- Keep the symlink and outside-root refusal, but a refusal is a **skip with a warning**, never an uncaught exception that aborts startup.
- Also make a UUID-named file that fails metadata reading (corrupt or partial) a skip with a warning, not a crash and not a delete.
- Update ADR-0006 to state: "reconciliation only adds rows; it never removes files".

**Tests:**
- `test_startup_reconcile_never_deletes_unrecognised_audio_files`: non-UUID `.mp3` and `.ogg` files at the root and in date subfolders still exist with identical bytes after `create_app` lifespan start and stop, and no rows are added for them.
- `test_startup_reconcile_skips_corrupt_uuid_file_without_crashing`: a zero-byte or garbage `<uuid>.mp3` doesn't abort startup, keeps its bytes, and is logged.

## B. Shutdown still leaks unowned tasks
**PM probe on your tree:**
1. `PersistenceSubscriber` with a 1 s commit in flight.
2. `stop()` while `_busy` returned in **0.00 s** and set `_task = None`.
3. Afterwards `asyncio.all_tasks()` still held `tonewatch-persistence` (the subscriber loop, which never exits) and `tonewatch-persistence-commit`, with no owner.

`Supervisor.stop()` likewise returns while `tonewatch-shutdown-drain` may still be running. The lifespan then calls `engine.dispose()` underneath it.

**Fix:** shutdown must end with **zero ToneWatch-owned tasks still running**, within `shutdown_finalize_timeout_s + shutdown_drain_timeout_s` (plus a small, documented epsilon).
- `PersistenceSubscriber.stop()` lets an in-flight commit finish **up to the drain budget**, then cancels and awaits the loop task. It never drops the reference.
- If the commit outlives the budget, cancel it and log `persistence commit abandoned at shutdown`. ADR-0006 option (b) reconciles the file on next start.
- `Supervisor.stop()` awaits or cancels its shutdown-drain task before returning, and `_background_shutdown` must be empty when `stop()` returns.
- The app lifespan disposes the engine only after `supervisor.stop()` has returned with nothing pending.

**Tests:**
- `test_persistence_stop_while_busy_leaves_no_pending_tasks`: a 1 s commit with a 0.2 s budget. After `stop()`, no `asyncio.all_tasks()` entry is named `tonewatch-*`, and elapsed is < 0.5 s.
- `test_app_shutdown_leaves_no_tonewatch_tasks`: through `create_app` lifespan with a slow encoder and a slow commit beyond both budgets. After lifespan exit, no `tonewatch-*` task is pending, elapsed is ≤ finalize + drain + 0.5 s, and a restart reconciles the recording row.
- Keep your three existing tests passing, and run each new test 10× in a loop; show the pass count.

## Constraints and definition of done
- Stay in `backend/` and `docs/`.
- No `pragma: no cover`, no `mark.skip`, no lowered gates (`pipeline` ≥95, `recording` ≥90).
- Each new test must fail on your current tree first. Quote one failure line each.
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Then run `just check` **last** and paste its unfiltered tail.
- Final message: a **finding → fix (file:function) → test** table.
