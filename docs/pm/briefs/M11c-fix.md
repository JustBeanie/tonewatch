# Brief: M11c-fix — one URL helper, a hardened proxy, and repairs that live outside diagnostics

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0c1e2-39f8-7f31-9121-e83e8e0001da`) · **Model:** gpt-5.6-luna, medium
**Work dir:** `C:\Users\beanie\Documents\Proj\ha-tonewatch`, **branch `m11c-media`** (your uncommitted work stays). `docs/pm/briefs/M11c-media-diagnostics.md` still applies.

## PM review
Media browsing, the proxy, diagnostics redaction, repairs and both blueprints are there. Fix the following, then the PM pushes and CI runs the tests. You still cannot run pytest on Windows; say so again in your report.

1. **`_recording_url` is duplicated three times and reached into privately.**
   - It exists on `ToneWatchEntity` (`entity.py:67`) **and** on the coordinator (`api.py:298`), and `media_source.py:209` constructs a throwaway `ToneWatchEntity(coordinator, "media", "proxy")` just to call the private method.
   - Extract **one** public helper (e.g. `def recording_url(base_url: str, value: Any) -> str | None` in a new `urls.py`), and call it from the entity, the coordinator and the view. Delete both private copies. Constructing an entity outside a platform is wrong: it has no `hass`, and it would break the moment the base class touches one.
2. **Harden the proxy (`ToneWatchMediaView.get`):**
   - Wrap the upstream request in a timeout (`aiohttp.ClientTimeout`, e.g. 30 s total, and no timeout cap on the body stream beyond a sock-read timeout).
   - Map failures: `aiohttp.ClientError`/`TimeoutError` to **502**, and an upstream 404 to **404**. Right now any upstream failure becomes an unhandled 500.
   - Forward the upstream status faithfully for 206 and 416.
   - Also forward `If-Range` and `Accept-Encoding: identity` upstream, so seeking works.
   - Keep the response header allowlist, and confirm the ToneWatch token is in no forwarded header.
   - `recording_id.isdigit()` assumes numeric ids. Confirm that against the app's `Recording.id` type (`backend/src/tonewatch/storage/models.py`); if it can ever be non-numeric, validate against the real shape instead. Say which you verified.
3. **Repairs belong in the integration runtime, not `diagnostics.py`.** `async_create_issue`/`async_delete_issue` currently sit in the diagnostics module, which HA only imports when a user downloads diagnostics. Move the version-mismatch and long-disconnect issues to where they are evaluated on a real signal (setup and coordinator connection changes), and keep `diagnostics.py` to the redacted dump. Add a test that the issue is created **without** anyone calling diagnostics.
4. **Test the sad paths** added above: a 502 on upstream error, a 404 on upstream 404, a Range request forwarded and a 206 returned.

## Evidence
- The single helper's location, and proof (grep) that no other copy remains.
- The proxy failure-mapping tests, and the repairs test that does not touch diagnostics.
- `ruff` and `mypy` output, and `git diff --stat`. Never write git state.
- **Honesty rule:** as always. Do not claim pytest or coverage results you did not run.

## Standing rules
- As in M11c. The app repo is read-only reference.
