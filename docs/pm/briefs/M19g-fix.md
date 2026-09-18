# Brief: M19g-fix — the support bundle leaks through health errors, URLs and Windows paths, and production code carries test seams

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b605-7a2a-79c1-9467-b4a0de5ab3af`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19g` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8844`. `docs/pm/briefs/M19g-support-logs.md` still applies in full.

## PM review
The ring and the API are a reasonable start, but the bundle's secrecy rests on a denylist of key names, and several real leak paths remain. Your test C seeded only the fields you had denylisted. **Write a failing test first for each item and paste its failing line as you go**, in case your turn is cut off.

### Leaks (the main work)
1. **`health.json` goes into the bundle unfiltered.**
   - Source and output `last_error` strings come from exceptions, so they can contain a stream URL with credentials (`http://user:pass@host/...`), a webhook URL, an MQTT host or a file path.
   - **Fix:** run **every** bundle file (config, health, logs, detections, environment) through one final text scrubber, applied to the **structured values before serialization**, not only a byte replace afterwards:
     - URLs: drop userinfo and query strings, keep the scheme and host-class only (e.g. `https://[host]/…`)
     - known secrets: the current and previous API token, the live secret, and every non-empty secret value found in the config via `is_secret_key`
     - the data dir and the user's home directory
2. **Key-name denylist gaps in `config.redacted.yaml`:**
   - `tile_url` (map tile URLs often carry an API key in the query)
   - `username` fields (MQTT, CAD feed and Meshtastic)
   - file source `path` (reveals local folders)
   - stream `url` (credentials or tokens)

   Webhook `url` is already covered. **Fix:** redact **any** string value that parses as a URL, whatever its key. Redact `username` and file `path`, leaving a basename at most (not a folder).
3. **The data dir replacement fails on Windows.**
   - `content.replace(str(data_dir).encode(), ...)` runs **after** `json.dumps`, and `json.dumps` escapes backslashes. So `C:\Users\...` never matches `C:\\Users\\...` in `health.json`/`logs.jsonl`.
   - Item 1's structured scrub fixes this. Also normalize both slash styles.
   - **Test:** use a data dir containing a backslash-style absolute path (build it with `PureWindowsPath` strings in a fixture value if needed), and prove it never appears in any file, in either escaped or raw form.
4. **Make test C model-driven, so it can't be satisfied by a denylist.**
   - Build the fixture config by walking `AppConfig`'s model fields recursively. Fill **every** `str`/`AnyUrl`/`SecretStr`-like field with a unique sentinel (URL-typed fields get `https://sentinel-user:sentinel-pass@sentinel-host-N.invalid/p?k=sentinel-q-N`).
   - Seed health errors (a source `last_error` and an output `last_error`) that contain a credentialed URL, plus a log record containing one.
   - Then assert no sentinel secret, password, username, query value, host or home/data path appears in any bundle file.
   - An explicit **allowlist** of fields that may appear (ids, names, enums, numbers, booleans, frequencies) is fine, and it must be written down in the test.

### Code quality
5. **Test seams in production code:**
   - `LogRingHandler.setStream` exists only as a "test seam". Remove it and fix whatever test needed it.
   - `configure_logging` installs the ring handler only when `ring` or `token_holder` is passed, a gate that exists for tests. Install it always.
   - `RenderSizeFilter.filter` has a duplicated docstring.
6. Use `logging.getLevelNamesMapping()` instead of the private `logging._nameToLevel`. An unknown `level` query value gives **422**, not a silent NOTSET.
7. `environment.json` detects Docker via a `.docker` file in the data dir, which is wrong. Use the documented add-on/settings flags or `/.dockerenv`, or drop the Docker flag if you can't detect it reliably, and say which you chose.

## Evidence (the report is rejected without it)
- A table mapping items 1–7 to their tests, with the failing line before the fix and the passing line after.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api` at least 1 % above the gate.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19g. **Parallel engineers:** M19f is in `api/deps.py`, `api/routes/admin.py` (config history routes; keep your admin.py edits confined to the support/logs section), `config/history.py` and `api/app.py`; M19h is in `web/**` and `api/routes/audit.py`. Moving the support/logs routes into a new `api/routes/support.py` is **preferred** and avoids the conflict; if you do it, register it with one line in `api/app.py`.
