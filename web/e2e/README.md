# ToneWatch end-to-end tests

The Playwright suite runs against one real ToneWatch HTTP server. Playwright's
`webServer` starts `e2e/start.mjs`; the launcher builds the SPA, creates a WAV
with `tonewatch.dsp.generator`, writes a valid file-source configuration, and
starts `tonewatch serve` with the UI password in its environment. The backend
serves both the API and built SPA on port 8765.

The launcher does not proxy, intercept, rewrite, mock, or inject any browser
request or response. Playwright observes the backend's real WebSocket and
recording responses. Playwright owns teardown; on Windows the launcher handles
SIGTERM, SIGINT, and stdin close and uses `taskkill /T` to remove the backend
process tree.

Run from the repository root with `just e2e`. On Windows the recipe selects
the installed Chrome channel, while CI installs and uses bundled Chromium.
