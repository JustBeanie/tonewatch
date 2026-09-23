# Brief: M11d — M11.8 quality pass: Home Assistant Silver rules, coverage and release readiness (ha-tonewatch)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11d-silver`** (the PM created it from the merged `main`; it is clean).
**Git:** never write git state. The PM commits, pushes and opens the PR.
**You cannot run pytest on Windows** (HA imports Unix-only `fcntl`, and `lru-dict` needs MSVC). Write tests by reading the existing ones; CI on Linux verifies. Never claim pytest or coverage results you did not run.

## Read first
- The whole integration: `custom_components/tonewatch/` and `tests/`.
- The Home Assistant **integration quality scale** rules, Bronze and Silver tiers, in the HA developer docs. Work from the published rule list, not memory.
- `.github/workflows/ci.yml`, `pyproject.toml` (the 90 % `--cov-fail-under`), `hacs.json`, `README.md`.

## Required
1. **Write `quality_scale.yaml`** in `custom_components/tonewatch/`, listing every Bronze and Silver rule with `done`, `exempt` (with a reason) or `todo`. Be honest: a rule you have not met is `todo`, not `done`.
2. **Close the Bronze and Silver gaps you can close in this slice.** Expect these to need work, but verify each against the real rule list:
   - `config-flow-test-coverage`: the config flow must be covered end to end, including every abort and error path, and reauth.
   - `entity-unavailable`, `entity-unique-id`, `has-entity-name`, `entity-device-class`, `entity-translations`: audit every platform; add device classes and translation keys where they fit (for example `sensor.last_call` is a timestamp, feed health is connectivity).
   - `action-exceptions`: service and entity actions must raise `HomeAssistantError` (or a subclass) on failure, not bare exceptions. The switch write and the test button are the cases here.
   - `reauthentication-flow`, `test-before-setup`, `test-before-configure`: confirm each exists and is tested.
   - `log-when-unavailable`: log once when the connection drops and once when it returns, not on every retry.
   - `parallel-updates`: set `PARALLEL_UPDATES` on each platform.
   - `integration-owner`, `docs-*`: the README must cover installation through HACS, configuration, the entities, the media source, the blueprints, troubleshooting and removal.
3. **Raise coverage** to at least **95 %** (the gate stays 90 %; the margin is the point), with behavioural tests, not line-touching ones.
4. **`manifest.json`:** `version` is `0.1.0` while the integration now has entities, media source and blueprints. Bump it to `0.2.0` and note it in the README, keeping `hacs.json` consistent.
5. **CI:** confirm the workflow runs hassfest, HACS validation, ruff, mypy strict and pytest with coverage on a supported HA version, and that all actions stay pinned to commit SHAs. Add anything missing from the M11.8 list.

## Mandatory tests (write first where they are new)
- Config flow: user, zeroconf, Supervisor discovery, reauth, duplicate abort, and every error branch (bad token, unreachable host, unexpected response).
- Each platform's unavailable behaviour.
- The switch and the button raising `HomeAssistantError` on an API failure.
- The "logged once" behaviour on disconnect and reconnect (`caplog`).

## Evidence (the report is rejected without it)
- The completed `quality_scale.yaml`, and a short table of what you changed to move a rule from `todo` to `done`.
- The uncovered lines you targeted, and the coverage figure you expect.
- `ruff` and `mypy` output. `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or the app repo. No new runtime dependencies. Never weaken a gate or lower the coverage floor.
