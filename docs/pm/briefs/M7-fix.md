# PM review: M7 fails on two spec issues and one hidden production defect

The alert subsystem is well built. All 19 named tests exist, there are no suppressions, TM-023 and TM-026 are updated, and `just check` and `just security` pass (PM re-verified). Fix exactly these three problems.

## 1. The migration was edited in place (data-loss / upgrade bug)
You added `phase` to `AlertAttempt` by editing `storage/migrations/versions/0001_initial.py`. Every database created before this change (every M3–M6 install) is already stamped at revision `0001`. Alembic will never apply the column, and dispatcher inserts then fail with "no such column".
- Revert `0001_initial.py` exactly to `HEAD`.
- Add `0002_alert_attempt_phase.py`, with `down_revision="0001"`. It adds `phase VARCHAR(40) NOT NULL DEFAULT 'unknown'` using `batch_alter_table`, which SQLite needs, plus a downgrade.
- **`test_upgrade_from_0001_database_adds_phase_column`:**
  1. Create a DB, upgrade it to `0001` only, and insert an `alert_attempts` row the old way.
  2. Upgrade to head.
  3. Assert the column exists, the old row reads `phase == 'unknown'`, and a new insert with a phase works.
- Keep `test_initial_migration_matches_metadata` passing; it should compare head against the metadata.

## 2. The MQTT test never uses the network
`test_mqtt_publishes_call_and_health_with_lwt` injects an in-process fake `Broker`/`Client` through `client_factory`, so `aiomqtt` and the MQTT wire protocol are never exercised. Add a **real** test, and keep the fake as a unit test:
- **`test_mqtt_real_broker_call_health_lwt_and_discovery`** in `backend/tests/integration/test_mqtt_broker.py`:
  1. Start an `amqtt` broker on `127.0.0.1` with an ephemeral port, in the test's event loop.
  2. Run `MqttAlertTarget` with the **default** `aiomqtt.Client` factory.
  3. Subscribe a separate real `aiomqtt` client to `tonewatch/#` and `homeassistant/#`.
  4. Drive a detection through the dispatcher.
  5. Assert the received retained availability `online`, the call payload, the health payload and the discovery configs.
  6. Stop the target and assert the LWT or `offline` is delivered, and that deleting a tone set clears its retained discovery.
- **On Windows** `aiomqtt` can't run on the Proactor loop, so mark the test `pytest.mark.skipif(sys.platform == "win32", reason="aiomqtt requires a selector loop; covered on Linux CI")`. The Linux and ARM CI jobs must run it. State in your report that you verified this, for example by running under WSL if available, or by writing `PENDING-CI`.

## 3. MQTT won't work in the native Windows build (production defect)
The same Proactor limitation means MQTT alerts fail at runtime on Windows (M9 native build). You can't switch the whole app to a selector loop: subprocesses (`rtl_fm`, script targets) **require** Proactor on Windows.
- **Fix:** on `sys.platform == "win32"`, `MqttAlertTarget` runs its aiomqtt client in a dedicated background thread that owns an `asyncio.SelectorEventLoop`. Messages cross between the app loop and that thread with `asyncio.run_coroutine_threadsafe` / `loop.call_soon_threadsafe`, through a bounded outbox. Lifecycle: start, stop, join on shutdown, no leaked thread.
- On other platforms, keep running in the main loop.
- **`test_mqtt_windows_runs_client_in_selector_loop_thread`:** force the Windows code path with monkeypatch on any OS. Assert the client coroutine executes on a thread other than the main thread, with a `SelectorEventLoop`. Assert publishes from the main loop arrive (use the fake client here), and that stop joins the thread.
- **Windows real-broker smoke:** `test_mqtt_real_broker_via_selector_thread` runs **on Windows only**. It starts an `amqtt` broker inside the selector-loop thread too, and proves an actual publish round-trips on Windows. If amqtt itself can't run there, say so and use `paho-mqtt`'s pure-socket broker-less loopback, or skip with a documented reason.

## Constraints
You are in the `m7-alerts` worktree; stay in `backend/` and `docs/`. Keep `alerts/` coverage ≥90% per module (it's currently 90.09%, so add tests rather than relying on the margin).

## Definition of done
- `just check` exits 0; run it last and paste the unfiltered tail.
- `just security` exits 0.
- `grep -rn "pragma: no cover" backend/src` is empty.
- `git diff HEAD -- backend/src/tonewatch/storage/migrations/versions/0001_initial.py` is empty.
- The final message has a claim → test table for the 3 findings.
